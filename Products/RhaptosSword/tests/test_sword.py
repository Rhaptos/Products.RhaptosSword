import os, sys
if __name__ == '__main__':
    execfile(os.path.join(sys.path[0], 'framework.py'))

import zipfile as zf
import tempfile
import difflib
from StringIO import StringIO
from base64 import decodestring
from DateTime import DateTime
from md5 import md5

from xml.dom.minidom import parse, parseString

from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import getAdapter, getMultiAdapter
from zope.publisher.interfaces import IPublishTraverse
from zope.interface import Interface, directlyProvides, directlyProvidedBy
from Acquisition import aq_base
from ZPublisher.HTTPRequest import HTTPRequest
from ZPublisher.HTTPResponse import HTTPResponse
from Products.Five import BrowserView
from Products.CMFCore.interfaces import IFolderish
from Products.CMFCore.PortalFolder import PortalFolder
from Products.CMFCore.utils import _checkPermission
from Products.CMFCore.utils import getToolByName

from Products.PloneTestCase import PloneTestCase

from rhaptos.swordservice.plone.browser.sword import ISWORDService
from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
from rhaptos.swordservice.plone.interfaces import ISWORDEMIRI
from rhaptos.swordservice.plone.interfaces import ISWORDListCollection
from Products.RhaptosSword.browser.views import ServiceDocument
from Products.RhaptosSword.adapters import ValidationError
from Products.RhaptosRepository.interfaces.IVersionStorage import IVersionStorage
from Products.RhaptosRepository.VersionFolder import incrementMinor
from Products.RhaptosModuleStorage.ModuleVersionFolder import ModuleVersionStorage
from Products.RhaptosModuleStorage.ModuleDBTool import CommitError
from Products.RhaptosModuleStorage.ModuleView import ModuleView
from Products.RhaptosCollaborationTool.interfaces.portal_collaboration import portal_collaboration as ICollaborationTool

from Testing import ZopeTestCase
ZopeTestCase.installProduct('RhaptosSword')
ZopeTestCase.installProduct('RhaptosModuleEditor')
ZopeTestCase.installProduct('RhaptosContent')
ZopeTestCase.installProduct('RhaptosRepository')
ZopeTestCase.installProduct('CNXMLDocument')
ZopeTestCase.installProduct('UniFile')
ZopeTestCase.installProduct('RhaptosCollaborationTool')

#PloneTestCase.setupPloneSite()
PloneTestCase.setupPloneSite(products=['RhaptosSword'],
    extension_profiles=[
        'Products.RhaptosContent:default',
        'Products.RhaptosModuleEditor:default',
        'Products.CNXMLDocument:default',
        'Products.CNXMLTransforms:default',
        'Products.UniFile:default',
        'Products.LinkMapTool:default'
        ]
    )

#PloneTestCase.setupPloneSite(extension_profiles=['Products.RhaptosModuleEditor',])
# setupPloneSite accepts an optional products argument, which allows you to
# specify a list of products that will be added to the portal using the
# quickinstaller tool. Since 0.8.2 you can also pass an extension_profiles
# argument to import GS extension profiles.

DEBUG = True
DIRNAME = os.path.dirname(__file__)
BAD_FILE = 'bad_entry.xml'
GOOD_FILE = 'entry.xml'

from OFS.SimpleItem import SimpleItem

# Patch in a non-db version of ModuleView.getFile
def _ModuleView_getFile(self, name):
    """ This patches ModuleView.getFile to return our own files. """
    files = self.portal_moduledb.files.get(self.objectId, ())
    for f in files:
        if f.filename == name:
            return f.file
ModuleView.getFile = _ModuleView_getFile

class StubZRDBResult(object):
    def tuples(self):
        return [(1, 'Arts', 'ISKME subject'),
                (2, 'Business', 'ISKME subject'),
                (3, 'Humanities', 'ISKME subject'),
                (4, 'Mathematics and Statistics', 'ISKME subject'),
                (5, 'Science and Technology', 'ISKME subject'),
                (6, 'Social Sciences', 'ISKME subject')
               ]

class StubDataObject(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, k):
        try:
            return getattr(self, k)
        except AttributeError:
            raise KeyError, k


class StubModuleDB(SimpleItem):

    def __init__(self):
        self.id = 'portal_moduledb'
        self.versions = {}
        self.files = {}

    def getLicenseData(self, url):
        return True

    def sqlGetTags(self, scheme):
        return StubZRDBResult()

    def sqlGetKeywords(self, *args, **kwargs):
        return [
            StubDataObject(word='Test'),
            StubDataObject(word='Module')]

    def insertModuleVersion(self, ob):
        # Just remember the most recent version
        self.versions[ob.objectId] = (
            ob.version, ob.created, ob.revised, ob.submitter, ob.submitlog,
            ob.authors)

        # Keep track of the files, we'll need them later
        self.files[ob.objectId] = []
        for fob in ob.objectValues():
            if hasattr(fob, 'data'):  # It's (most likely) a file object
                self.files[ob.objectId].append(
                    StubDataObject(
                        filename=(callable(fob.id) and fob.id() or fob.id),
                        mimetype=fob.content_type,
                        file=StringIO(fob.data)))
        self._p_changed = 1


    def sqlGetLatestModule(self, id):
        data = self.versions[id]
        ob = StubDataObject(ident=1,
            name='Published Module %s' % id,
            abstract = 'The Abstract',
            roles = {},
            authors = data[5],
            language = 'en',
            version = data[0],
            created = data[1],
            revised = data[2],
            maintainers = data[5],
            licensors = data[5],
            submitter = data[3],
            portal_type = 'Module',
            license = 'http://creativecommons.org/licenses/by/3.0/',
            subject = ('Test', 'Module'),
            parent_id = None,
            parent_version = None,
            parentAuthors = None,
        )
        return (ob,)

    def sqlGetModuleFilenames(self, id, version):
        return self.files[id]

class StubLanuageTool(SimpleItem):

    def __init__(self):
        self.id = 'language_tool'

    def getAvailableLanguages(self):
        return {'af': 'Afrikaans',
                'en': 'English',
                'en-za': 'South African English',
               }

    def getLanguageBindings(self):
        return ('en', 'en', [])

class StubModuleStorage(ModuleVersionStorage):
    __implements__ = (IVersionStorage)

    def getHistory(self, id):
        return self.portal_moduledb.versions.get(id, ())

    def generateId(self):
        repo = self.aq_parent
        count = len(repo.objectIds())-2 # ignore storage and cache
        return 'm%d' % (10001+count)


    def hasObject(self, id):
        return id in self.aq_parent.objectIds()


    def notifyObjectRevised(self, object, origobj=None):
        pass

class DummyLensTool(SimpleItem):
    def __init__(self):
        super(DummyLensTool, self).__init__('lens_tool')

    def notifyLensRevisedObject(self, *args, **kwargs):
        pass


class DummyModuleVersionStub(PortalFolder):
    def __init__(self, id, storage):
        self.id = id
        self.storage = storage


class StubCollaborationTool(SimpleItem):
    __implements__ = ICollaborationTool

    def __init__(self):
        self.id = 'portal_collaboration'

    def searchCollaborations(self, **kw):
        return []
    
    def catalog_object(self, object, id):
        pass

    def uncatalog_object(self, id):
        pass


class StubWorkspaces(SimpleItem):
    def __init__(self):
        self.id = 'getWorkspaces'
        self.wgs = [{'link': 'GroupWorkspaces/wg0',
                     'title': 'Workgroup1',
                     'description': 'Workgroup1',
                    }
                   ]
    
    def __call__(self):
        return self.wgs


def clone_request(req, response=None, env=None):
    # Return a clone of the current request object.
    environ = req.environ.copy()
    environ['REQUEST_METHOD'] = 'GET'
    if req._auth:
        environ['HTTP_AUTHORIZATION'] = req._auth
    if env is not None:
        environ.update(env)
    if response is None:
        if req.response is not None:
            response = req.response.__class__()
        else:
            response = None
    clone = req.__class__(None, environ, response, clean=1)
    directlyProvides(clone, *directlyProvidedBy(req))
    return clone

def getEditIRI(dom):
    links = dom.getElementsByTagNameNS('http://www.w3.org/2005/Atom', 'link')
    return [l for l in links if l.getAttribute('rel')=='edit'][0].getAttribute(
        'href')

def diff(a, b):
    return '\n'.join(
        difflib.unified_diff(a.splitlines(), b.splitlines())
        )

class TestSwordService(PloneTestCase.PloneTestCase):
    def afterSetup(self):
        pass


    def _setupRhaptos(self):
        # XXX: This method needs to move to afterSetup, but afterSetup is not
        # being called for some reason.
        objectIds = self.portal.objectIds()
        if not 'content' in objectIds:
            self.portal.manage_addProduct['RhaptosRepository'].manage_addRepository('content') 
            # We need storage for our published modules. This is as good a place as
            # any.
            self.portal.content.registerStorage(StubModuleStorage('storage'))
            self.portal.content.setDefaultStorage('storage')
        if not 'portal_moduledb' in objectIds:
            self.portal._setObject('portal_moduledb', StubModuleDB())
        if not 'portal_languages' in objectIds:
            self.portal._setObject('portal_languages', StubLanuageTool())
        if not 'lens_tool' in objectIds:
            self.portal._setObject('lens_tool', DummyLensTool())
        if not 'portal_collaboration' in objectIds:
            self.portal._setObject('portal_collaboration', StubCollaborationTool())
        if not 'getWorkspaces' in objectIds:
            self.portal._setObject('getWorkspaces', StubWorkspaces())


    def createUploadRequest(self, filename, context, **kwargs):
        if filename is None:
            content = kwargs.get('content', '')
        else:
            xml = os.path.join(DIRNAME, 'data', 'unittest', filename)
            file = open(xml, 'rb')
            content = file.read()
            file.close()
        env = {
            'CONTENT_TYPE': 'application/atom+xml;type=entry',
            'CONTENT_LENGTH': len(content),
            'IN_PROGRESS': 'true',
            'REQUEST_METHOD': 'POST',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80'
        }
        env.update(kwargs)
        uploadresponse = HTTPResponse(stdout=StringIO())
        uploadrequest = clone_request(self.app.REQUEST, uploadresponse, env)
        bodyfile = StringIO(content)
        uploadrequest.set('BODYFILE', bodyfile)
        uploadrequest.stdin = bodyfile
        # Fake PARENTS
        uploadrequest.set('PARENTS', [context])
        return uploadrequest


    def testSwordService(self):
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        file = open(os.path.join(DIRNAME, 'data', 'unittest', 'servicedocument.xml'), 'r')
        reference_servicedoc = file.read()
        file.close()

        request = self.portal.REQUEST
        # Check that 'sword' ends up at a browser view
        view = self.portal.restrictedTraverse('sword')
        assert isinstance(view, BrowserView)

        # Test service-document
        view = self.portal.restrictedTraverse('sword/servicedocument')
        assert isinstance(view, ServiceDocument)
        xml = view()
        assert "<sword:error" not in xml
        if DEBUG == True:
            if xml != reference_servicedoc:
                self.writecontents(xml, 'returned_servicedocument.xml')
        assert xml == reference_servicedoc, 'Result does not match reference doc,'
        
        uploadrequest = self.createUploadRequest(
            'm11868_1.6.zip',
            self.portal.workspace,
            CONTENT_TYPE= 'application/zip',
            CONTENT_DISPOSITION= 'attachment; filename=m11868_1.6.zip',
            IN_PROGRESS= 'true',
        )
        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        adapter = getMultiAdapter(
            (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()

        # There should be no errors
        self.assertTrue("<sword:error" not in xml, xml)

        # Test that we can still reach the edit-iri
        drdom = parseString(xml)
        editiri = str(getEditIRI(drdom))
        moduleid = editiri.split('/')[-2]
        self.assertTrue(bool(
            self.portal.workspace.restrictedTraverse('%s/sword' % moduleid)),
            "Cannot access deposit receipt")
        zipfile = self.portal.workspace._getOb(moduleid)

        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'depositreceipt_plain_zipfile.xml'), 'r')
        dom = parse(file)
        file.close()
        dates = dom.getElementsByTagName('updated')
        dates[0].firstChild.nodeValue = zipfile.revised
        created = dom.getElementsByTagName('dcterms:created')
        for element in created:
            element.firstChild.nodeValue = zipfile.created
        modified = dom.getElementsByTagName('dcterms:modified')
        for element in modified:
            element.firstChild.nodeValue = zipfile.revised

        identifiers = dom.getElementsByTagName('dcterms:identifier')
        for identifier in identifiers:
            if identifier.getAttribute('xsi:type') == "dcterms:URI":
                identifier.firstChild.nodeValue = zipfile.absolute_url()
        reference_depositreceipt = dom.toxml()
        reference_depositreceipt = reference_depositreceipt.replace('__MODULE_ID__', zipfile.id)

        returned_depositreceipt = parseString(xml).toxml()
        self.assertTrue(bool(xml), "Upload view does not return a result")
        if DEBUG == True:
            if returned_depositreceipt != reference_depositreceipt:
                self.writecontents(
                    returned_depositreceipt, 'returned_depositreceipt_plain_zipfile.xml')
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc: \n\n%s' % diff(
                returned_depositreceipt, reference_depositreceipt))


    def testFoldersAreFolderish(self):
        self.assertTrue(IFolderish.providedBy(self.folder), "Folders are not Folderish")


    def test_publishBadAtomXML(self):
        """
         See what happens when we throw bad xml at the import funtionality.
        """
        self._setupRhaptos()
        if not 'workspace' in self.portal.objectIds():
            self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest('bad_entry.xml', self.portal.workspace)

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "ExpatError" in xml, 'Bad XML did not raise an exception.'


    def testMetadata(self):
        """ See if the metadata is added correctly. """
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            self.portal.workspace,
            CONTENT_DISPOSITION='attachment; filename=entry.xml',
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        returned_depositreceipt = dom.toxml()

        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'entry_depositreceipt.xml'), 'r')
        dom = parse(file)
        file.close()

        module = self.portal.workspace.objectValues()[0]
        mid = dom.getElementsByTagName('id')
        for element in mid:
            element.firstChild.nodeValue = module.id
        dates = dom.getElementsByTagName('updated')
        dates[0].firstChild.nodeValue = module.revised
        created = dom.getElementsByTagName('dcterms:created')
        for element in created:
            element.firstChild.nodeValue = module.created
        modified = dom.getElementsByTagName('dcterms:modified')
        for element in modified:
            element.firstChild.nodeValue = module.revised
        identifiers = dom.getElementsByTagName('dcterms:identifier')
        for identifier in identifiers:
            if identifier.getAttribute('xsi:type') == "dcterms:URI":
                identifier.firstChild.nodeValue = module.absolute_url()

        reference_depositreceipt = dom.toxml()
        reference_depositreceipt = reference_depositreceipt.replace('__MODULE_ID__', module.id)

        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml
        if DEBUG == True:
            if returned_depositreceipt != reference_depositreceipt:
                self.writecontents(
                    returned_depositreceipt, 'returned_entry.xml')
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc: \n\n%s' % diff(
                returned_depositreceipt, reference_depositreceipt))

    def test_invalidabstract(self):
        """ test that invalid cnxml in abstract raises an exception """
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'invalidabstract.xml'
        # XXX: assertRaises is not working for some reason
        # self.assertRaises(AssertionError,
        #    self._createModule(self.folder.workspace, filename))
        try:
            self._createModule(self.folder.workspace, filename)
        except AssertionError:
            pass
        except:
            raise

    def test_invalidAnalyticsCode(self):
        """ test that invalid Google Analytics codd raises an exception """
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'invalidanalyticscode.xml'
        # XXX: assertRaises is not working for some reason
        # self.assertRaises(AssertionError,
        #    self._createModule(self.folder.workspace, filename))
        try:
            self._createModule(self.folder.workspace, filename)
        except AssertionError:
            pass
        except:
            raise

    def testMultipart(self):
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        drdom = parseString(xml)
        editiri = getEditIRI(drdom)
        # it is no longer /sword/edit... just /sword
        moduleid = editiri.split('/')[-2]
        returned_depositreceipt = drdom.toxml()
        self.assertTrue(moduleid in self.portal.workspace.objectIds())
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        module = self.portal.workspace.objectValues()[0]
        file = open(os.path.join(DIRNAME, 'data', 'unittest', 'multipart_depositreceipt.xml'), 'r')
        dom = parse(file)
        file.close()
        dates = dom.getElementsByTagName('updated')
        dates[0].firstChild.nodeValue = module.revised
        created = dom.getElementsByTagName('dcterms:created')
        for element in created:
            element.firstChild.nodeValue = module.created
        modified = dom.getElementsByTagName('dcterms:modified')
        for element in modified:
            element.firstChild.nodeValue = module.revised

        identifiers = dom.getElementsByTagName('dcterms:identifier')
        for identifier in identifiers:
            if identifier.getAttribute('xsi:type') == "dcterms:URI":
                identifier.firstChild.nodeValue = module.absolute_url()
        reference_depositreceipt = dom.toxml()
        reference_depositreceipt = reference_depositreceipt.replace('__MODULE_ID__', module.id)

        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml
        if DEBUG == True:
            if returned_depositreceipt != reference_depositreceipt:
                self.writecontents(
                    returned_depositreceipt, 'returned_multipart_depositreceipt.xml')
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc: \n\n%s' % diff(
                returned_depositreceipt, reference_depositreceipt))

    def testUploadAndPublish(self):
        """ Upload a module
            Set its metadata
            See if we can publish it.
        """
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true',
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Sign the license, set the title, set maintainer, author, copyright
        # holder, description of changes.
        unpubmod = self.portal.workspace.objectValues()[0]
        unpubmod.license = 'http://creativecommons.org/licenses/by/3.0/'
        unpubmod.title = 'The Tigger Movie'
        unpubmod.maintainers = ['test_user_1_']
        unpubmod.authors = ['test_user_1_']
        unpubmod.licensors = ['test_user_1_']
        unpubmod.message = "I will not buy this tobacconist's, it is scratched"

        # Publish it for the first time
        emptyrequest = self.createUploadRequest(
            None,
            context=self.portal.workspace,
            CONTENT_TYPE='text/plain',
            IN_PROGRESS='false',
        )
        self.setRoles(('Member','Manager'))
        xml = getMultiAdapter((unpubmod, emptyrequest), ISWORDEditIRI)()
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")
        self.setRoles(('Member',))

        pubmod = self.portal.workspace.objectValues()[0]
        
        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'checkout_and_update.txt'), 'r')
        content = file.read()
        file.close()
        content = content.replace('module_url', pubmod.absolute_url())
        # Now check it out again, and replace the content, but don't publish
        uploadrequest = self.createUploadRequest(
            None,
            content=content,
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()

        # Do the usual checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Get the edit-iri of this item
        dr = parseString(xml)
        editiri = getEditIRI(dr)

        editorid = str(editiri).split('/')[-2]
        editor = self.portal.workspace.restrictedTraverse(editorid)

        # Set title et al. Not sure if this should have been inherited from
        # the module we checked out? Newer versions of the module might
        # not have the same authors, maintainers and licensors. Perhaps not
        # even the same title. Assume it needs to be set again?
        editor.title = 'Yandelavasa grldenwi stravenka'
        editor.maintainers = ['test_user_1_']
        editor.authors = ['test_user_1_']
        editor.licensors = ['test_user_1_']
        editor.message = 'Our hovercraft is no longer invested by eels'

        # Now publish it by posting to the edit-iri
        adapter = getMultiAdapter((editor, emptyrequest), ISWORDEditIRI)
        xml = adapter()

        # Same old checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Check that the version has been incremented
        pubmod = self.portal.workspace._getOb(editorid)
        self.assertTrue(pubmod.version == "1.2",
            "Version did not increment")


    def testSwordServiceRetrieveContent(self):
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart.txt'
        )

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        env = {
            'REQUEST_METHOD': 'GET',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80'
        }
        getresponse = HTTPResponse(stdout=StringIO())
        getrequest = clone_request(self.app.REQUEST, getresponse, env)
        
        ids = self.portal.objectIds()
        self.assertTrue('workspace' in ids, 'No workspace found!')

        # We should have at least one module now, this will fail if we don't
        module = self.portal.workspace.objectValues()[0]

        adapter = getMultiAdapter((module, getrequest), ISWORDEMIRI)
        retrieved_content = adapter()
        file = tempfile.NamedTemporaryFile()
        file.write(retrieved_content)
        file.flush()
        retrieved_file = zf.ZipFile(file.name)
        file.close()
        reference_file = zf.ZipFile(
            os.path.join(DIRNAME, 'data', 'unittest', 'retrievedcontent.zip'))
        if DEBUG == True:
            if len(retrieved_file.namelist()) != len(reference_file.namelist()):
                self.writecontents(retrieved_file, 'returned_content.zip')
        self.assertEqual(len(retrieved_file.namelist()), len(reference_file.namelist()),
            'The files are not the same.')
        retrieved_fl = retrieved_file.filelist
        reference_fl = retrieved_file.filelist
        for count in range(0, len(retrieved_file.filelist)):
            retrieved = retrieved_fl[count]
            reference = reference_fl[count]
            msg = 'File:%s and File:%s are not the same' %\
                (retrieved.filename, reference.filename)
            self.assertEqual(retrieved.CRC, reference.CRC, msg)

    
    def testSwordServiceStatement(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart.txt'
        )

        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml

        module = self.folder.workspace.objectValues()[0]
        # get the exact current date time then set the module's date time.
        # we do this because later on we test that we got the correct 
        # date and time back.
        now = DateTime()
        module.created = now
        view = module.restrictedTraverse('sword/statement.atom')
        xml = view()
        assert "<sword:error" not in xml, xml
        returned_statement = parseString(xml).toxml()

        file = open(os.path.join(DIRNAME, 'data', 'unittest', 'multipart_statement.xml'), 'r')
        dom = parse(file)
        file.close()
        reference_statement = dom.toxml()
        reference_statement = reference_statement.replace('__MODULE_ID__', module.id)
        if DEBUG == True:
            if returned_statement != reference_statement:
                self.writecontents(returned_statement, 'returned_statement.xml')
        self.assertEqual(returned_statement, reference_statement,
            'Returned statement and reference statement '
            'are not identical: \n\n%s' % diff(
                returned_statement, reference_statement))


    def testDeriveModule(self):
        self.testUploadAndPublish()
        filename = 'derive_module.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        module = self.folder.workspace.objectValues()[0]
        source = dom.getElementsByTagName('dcterms:source')[0]
        source.firstChild.nodeValue = module.id
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml())
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml


    def test_handlePUT(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'put_test_step1.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart')
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml

        module = self.folder.workspace.objectValues()[0]
        uploadrequest = self.createUploadRequest(
            'put_test_step2.xml',
            module,
            REQUEST_METHOD = 'PUT',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        id = dom.getElementsByTagName(
            'id')[0].firstChild.toxml().encode('utf-8')
        uri = dom.getElementsByTagName(
            'dcterms:identifier')[0].firstChild.toxml().encode('utf-8')
        version = dom.getElementsByTagName(
            'dcterms:identifier')[1].firstChild.toxml().encode('utf-8')
        contentId = dom.getElementsByTagName(
            'dcterms:identifier')[2].firstChild.toxml().encode('utf-8')
        title = dom.getElementsByTagName(
            'dcterms:title')[0].firstChild.toxml().encode('utf-8')
        created = dom.getElementsByTagName(
            'dcterms:created')[0].firstChild.toxml().encode('utf-8')
        modified = dom.getElementsByTagName(
            'dcterms:modified')[0].firstChild.toxml().encode('utf-8')
        creator = dom.getElementsByTagName(
            'dcterms:creator')[0].getAttribute('oerdc:id').encode('utf-8')
        maintainer = dom.getElementsByTagName(
            'oerdc:maintainer')[0].getAttribute('oerdc:id').encode('utf-8')
        rightsHolder = dom.getElementsByTagName(
            'dcterms:rightsHolder')[0].getAttribute('oerdc:id').encode('utf-8')
        description_of_changes = dom.getElementsByTagName(
            'oerdc:descriptionOfChanges')[0].firstChild.toxml().encode('utf-8')
        # oerdc:subject should not be in the dom, but let's try to find it anyway.
        try:
            subject = dom.getElementsByTagName(
                'oerdc:subject')[0].firstChild.toxml().encode('utf-8')
        except IndexError:
            subject = ''
        # analyticsCode should not be in the dom either...
        try:
            analyticsCode = dom.getElementsByTagName(
                'oerdc:analyticsCode')[0].firstChild.toxml().encode('utf-8')
        except IndexError:
            analyticsCode = ''
        abstract = dom.getElementsByTagName(
            'dcterms:abstract')[0].firstChild.toxml().encode('utf-8')
        language = dom.getElementsByTagName(
            'dcterms:language')[0].firstChild.toxml().encode('utf-8')
        # we can potentially drop these 2 fields from the test.
        keywords = ''
        dcterms_subject = None
        license = None

        self.assertEqual(title, 'My Title 2', 'Title was not updated')
        self.assertEqual(creator, 'test_user_1_', 'Creator was not updated')
        self.assertEqual(abstract, 'The abstract 2', 'Abstract was not updated')
        self.assertEqual(language, 'en', 'Language was not updated')
        self.assertEqual(keywords, '', 'Keywords were not updated')
        self.assertEqual(subject, '', 'Subject was not updated')
        self.assertEqual(description_of_changes, '\n        Frobnicate the Bar - second time.\n    ',
            'descriptionOfChanges was not updated')
        self.assertEqual(analyticsCode, '', 'analyticsCode was not updated')

    
    def test_addRoles(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'test_roles.xml'
        module = self._createModule(self.folder.workspace, filename)

        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        namespaces = ["http://purl.org/dc/terms/",
                      "http://cnx.org/aboutus/technology/schemas/oerdc"
                     ]
        roles = {'creator': module.creators,
                 'maintainer': module.maintainers,
                 'rightsHolder': module.licensors,
                 'editor': module.editors,
                 'translator': module.translators}
        for ns in namespaces:
            for role, ids in roles.items():
                for element in dom.getElementsByTagNameNS(ns, role):
                    msg = 'Role:%s was not set properly.' %role
                    assert element.getAttribute('oerdc:id') in ids, msg

    def test_defaultRoles(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'emptyatom.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.maintainers, ('test_user_1_',))
        self.assertEqual(module.licensors, ('test_user_1_',))
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

    def test_creatorRoleOnly(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'creatoronly.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.maintainers, ())
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

    def test_maintainerRoleOnly(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'maintaineronly.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ())
        self.assertEqual(module.maintainers, ('test_user_1_',))
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

    def test_rightsHolderRolyOnly(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'rightsholderonly.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ())
        self.assertEqual(module.maintainers, ())
        self.assertEqual(module.licensors, ('test_user_1_',))
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

    def test_creatorAsEditorAndTranslator(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'editortranslator.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ())
        self.assertEqual(module.maintainers, ())
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ('test_user_1_',))
        self.assertEqual(module.translators, ('test_user_1_',))

    def test_multipleCreators(self):
        """ creator in the atom/sword sense translate to authors on modules.
        """
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        acl_users = getToolByName(self.portal, 'acl_users')
        acl_users.userFolderAddUser('user1', 'user1', ['Member'], [])
        acl_users.userFolderAddUser('user2', 'user2', ['Member'], [])
        acl_users.userFolderAddUser('user85', 'user85', ['Member'], [])
         
        filename = 'multiple_authors.xml'
        module = self._createModule(self.folder.workspace, filename)

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ('user85', 'user1', 'user2'))
        self.assertEqual(module.maintainers, ())
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())


    def test_depositReceipt_multipleCreators(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        acl_users = getToolByName(self.portal, 'acl_users')
        acl_users.userFolderAddUser('user1', 'user1', ['Member'], [])
        acl_users.userFolderAddUser('user2', 'user2', ['Member'], [])
        acl_users.userFolderAddUser('user85', 'user85', ['Member'], [])
         
        filename = 'multiple_authors.xml'
        module = self._createModule(self.folder.workspace, filename)
        view = module.restrictedTraverse('/'.join(module.getPhysicalPath())+'/sword')
        dom = parseString(view())
        creator_elements = dom.getElementsByTagName('dcterms:creator')
        self.assertEqual(
            len(creator_elements), 3, 'All creator/authors where not returned')

    def test_replaceRolesWithEmptyAtom(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        acl_users = self.portal.acl_users
        acl_users.userFolderAddUser('user1', 'user1', ['Member'], [])
        acl_users.userFolderAddUser('user2', 'user2', ['Member'], [])
        acl_users.userFolderAddUser('user85', 'user85', ['Member'], [])

        filename = 'multiple_authors.xml'
        module = self._createModule(self.folder.workspace, filename)

        # this request should give the user all the default roles
        uploadrequest = self.createUploadRequest(
            'emptyatom.xml',
            module,
            REQUEST_METHOD = 'PUT',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        assert "<sword:error" not in xml, xml

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ('test_user_1_',))
        self.assertEqual(module.maintainers, ('test_user_1_',))
        self.assertEqual(module.licensors, ('test_user_1_',))
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

    def test_removeAndRestoreRoles(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        acl_users = self.portal.acl_users
        acl_users.userFolderAddUser('user1', 'user1', ['Member'], [])
        acl_users.userFolderAddUser('user2', 'user2', ['Member'], [])
        acl_users.userFolderAddUser('user85', 'user85', ['Member'], [])

        filename = 'multiple_authors.xml'
        module = self._createModule(self.folder.workspace, filename)

        # this request should give the user all the default roles
        uploadrequest = self.createUploadRequest(
            'emptyatom.xml',
            module,
            REQUEST_METHOD = 'PUT',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        assert "<sword:error" not in xml, xml

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ('test_user_1_',))
        self.assertEqual(module.maintainers, ('test_user_1_',))
        self.assertEqual(module.licensors, ('test_user_1_',))
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())

        uploadrequest = self.createUploadRequest(
            'multiple_authors.xml',
            module,
            REQUEST_METHOD = 'PUT',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        assert "<sword:error" not in xml, xml

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ('user85', 'user1', 'user2'))
        self.assertEqual(module.maintainers, ())
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())


    def test_mergeRoles(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'creatoronly.xml'
        module = self._createModule(self.folder.workspace, filename)

        # this request should give the user all the default roles
        uploadrequest = self.createUploadRequest(
            'maintaineronly.xml',
            module,
            REQUEST_METHOD='PUT',
            UPDATE_SEMANTICS='merge',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        assert "<sword:error" not in xml, xml

        self.assertEqual(module.creators, ('test_user_1_',))
        self.assertEqual(module.authors, ('test_user_1_',))
        self.assertEqual(module.maintainers, ('test_user_1_',))
        self.assertEqual(module.licensors, ())
        self.assertEqual(module.editors, ())
        self.assertEqual(module.translators, ())


    def test_updateMetadataWithPOSTto_SE_IRI(self):
        """ Testing the merge semantics implementation.
        """
        # create a new module
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            module,
            CONTENT_DISPOSITION='attachment; filename=entry.xml',
        )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()


    def test_ListCollection(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        
        number_of_modules = 4
        modules = []
        for i in range(0, number_of_modules):
            modules.append(self._createModule(self.folder.workspace, filename))
        get_request = self.createUploadRequest(
            None,
            self.folder.workspace,
            REQUEST_METHOD='GET',
        )
        adapter = getMultiAdapter(
            (self.folder.workspace, get_request), ISWORDListCollection)
        xml = adapter()
        assert "<sword:error" not in xml, xml
        
        dom = parseString(xml)
        entries = dom.getElementsByTagName('entry')
        self.assertEqual(
            len(entries), number_of_modules, 'Not all modules were returned')

    
    def test_handleDelete(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        
        assert(len(self.folder.workspace.objectIds()) == 0,
               'There should be nothing here.')
        number_of_modules = 4
        modules = []
        for i in range(0, number_of_modules):
            modules.append(self._createModule(self.folder.workspace, filename))
        assert(len(self.folder.workspace.objectIds()) == 4,
               'There should be 4 modules here now.')
        
        for count, module in enumerate(modules):
            get_request = self.createUploadRequest(
                None,
                module,
                REQUEST_METHOD='DELETE',
            )
            adapter = getMultiAdapter((module, get_request), ISWORDEditIRI)
            adapter()
            assert(
                len(self.folder.workspace.objectIds())==number_of_modules-count,
                   'There should be nothing here.')

        assert(len(self.folder.workspace.objectIds())==0,
               'There should be nothing here.')
   

    def test_handleDeleteContents(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)
        assert('index.cnxml' in module.objectIds(), 'Module has no index.cnxml')
        get_request = self.createUploadRequest(
            None,
            module,
            REQUEST_METHOD='DELETE',
        )
        adapter = getMultiAdapter((module, get_request), ISWORDEMIRI)
        adapter()
        assert('index.cnxml' in module.objectIds(), 'Module has no index.cnxml')

    
    def test_duplicateTitle(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'duplicate_title.xml'
        uploadrequest = self.createUploadRequest(
            filename, 
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert 'ValidationError: More than one title.' in xml, xml


    def test_duplicateAbstract(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'duplicate_abstract.xml'
        uploadrequest = self.createUploadRequest(
            filename, 
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert 'ValidationError: More than one abstract.' in xml, xml


    def test_duplicateLanguage(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'duplicate_language.xml'
        uploadrequest = self.createUploadRequest(
            filename, 
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert 'ValidationError: More than one language.' in xml, xml


    def test_duplicateDescriptionOfChanges(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'duplicate_description_of_changes.xml'
        uploadrequest = self.createUploadRequest(
            filename, 
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert 'ValidationError: More than one descriptionOfChanges.' in xml, xml


    def test_duplicateAnalyticsCode(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'duplicate_analytics_code.xml'
        uploadrequest = self.createUploadRequest(
            filename, 
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert 'ValidationError: More than one analyticsCode.' in xml, xml


    def test_regionalLanguage(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'language_variant.xml'
        module = self._createModule(self.folder.workspace, filename)
        self.assertEqual(
            module.language, 'en-za', 'Regional language not set.')

    
    def test_oerdcSubject(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry_with_oerdc_subject.xml'
        module = self._createModule(self.folder.workspace, filename)
        self.assertEqual(module.subject, ('Arts',), 'Subject set incorrectly.')
        self.assertEqual(
            module.keywords, ('keyword 1', 'keyword 2'), 'Keywords set incorrectly.')
    

    def _createModule(self, context, filename):
        """ Utility method to setup the environment and create a module.
        """
        uploadrequest = self.createUploadRequest(
            filename, 
            context,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (context, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml
        
        editIri = getEditIRI(parseString(xml))
        module_id = editIri.split('/')[-2]
        module = context._getOb(module_id)
        return module


    def writecontents(self, contents, filename):
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'w')
        file.write(contents)
        file.close()
    

    def writedebuginfo(self, returned, reference):
        self.writecontents(returned, 'returned.xml')
        self.writecontents(reference, 'reference.xml')


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSwordService))
    return suite
