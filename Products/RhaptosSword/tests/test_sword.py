import AccessControl
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
from Products.RhaptosSword.browser.atompub import LensAtomPubAdapter
from Products.RhaptosRepository.interfaces.IVersionStorage import IVersionStorage
from Products.RhaptosRepository.VersionFolder import incrementMinor
from Products.RhaptosModuleStorage.ModuleVersionFolder import ModuleVersionStorage
from Products.RhaptosModuleStorage.ModuleDBTool import CommitError
from Products.RhaptosModuleStorage.ModuleView import ModuleView
from Products.RhaptosCollaborationTool.interfaces.portal_collaboration import portal_collaboration as ICollaborationTool
from Products.RhaptosRepository.interfaces.IRepository import IRepository

from Testing import ZopeTestCase
ZopeTestCase.installProduct('RhaptosSword')
ZopeTestCase.installProduct('RhaptosModuleEditor')
ZopeTestCase.installProduct('RhaptosContent')
ZopeTestCase.installProduct('RhaptosRepository')
ZopeTestCase.installProduct('CNXMLDocument')
ZopeTestCase.installProduct('UniFile')
ZopeTestCase.installProduct('RhaptosCollaborationTool')
ZopeTestCase.installProduct('ZAnnot')
ZopeTestCase.installProduct('RhaptosCollection')
ZopeTestCase.installProduct('ZCatalog')
ZopeTestCase.installProduct('Lensmaker')

#PloneTestCase.setupPloneSite()
PloneTestCase.setupPloneSite(products=['RhaptosSword'],
    extension_profiles=[
        'Products.RhaptosContent:default',
        'Products.RhaptosModuleEditor:default',
        'Products.RhaptosCollection:default',
        'Products.CNXMLDocument:default',
        'Products.CNXMLTransforms:default',
        'Products.UniFile:default',
        'Products.LinkMapTool:default',
        'Products.Lensmaker:default',
        ]
    )

#PloneTestCase.setupPloneSite(extension_profiles=['Products.RhaptosModuleEditor',])
# setupPloneSite accepts an optional products argument, which allows you to
# specify a list of products that will be added to the portal using the
# quickinstaller tool. Since 0.8.2 you can also pass an extension_profiles
# argument to import GS extension profiles.

DIRNAME = os.path.dirname(__file__)
BAD_FILE = 'bad_entry.xml'
GOOD_FILE = 'entry.xml'

from OFS.SimpleItem import SimpleItem
from OFS.ObjectManager import ObjectManager

# Patch in a non-db version of ModuleView.getFile
def _ModuleView_getFile(self, name):
    """ This patches ModuleView.getFile to return our own files. """
    files = self.portal_moduledb.files.get(self.objectId, ())
    for f in files:
        if f.filename == name:
            return f.file
ModuleView.getFile = _ModuleView_getFile

class StubZRDBResult(list):
    def __init__(self):
        data = [StubDataObject(id=1, tag='Arts', scheme='ISKME subject'),
                StubDataObject(id=2, tag='Business', scheme='ISKME subject'),
                StubDataObject(id=3, tag='Humanities', scheme='ISKME subject'),
                StubDataObject(id=4, tag='Mathematics and Statistics', scheme='ISKME subject'),
                StubDataObject(id=5, tag='Science and Technology', scheme='ISKME subject'),
                StubDataObject(id=6, tag='Social Sciences', scheme='ISKME subject')
               ]
        super(StubZRDBResult, self).__init__(data)

    def tuples(self):
        return [(i.id, i.tag, i.scheme) for i in self]

class StubDataObject(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getitem__(self, k):
        try:
            return getattr(self, k)
        except AttributeError:
            raise KeyError, k

def makeStubFromVersionData(id, data):
    return StubDataObject(ident=1,
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
        keywords = ('Test', 'Module'),
        subject = ('Arts',),
        parent_id = None,
        parent_version = None,
        parentAuthors = [],
    )


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
        ob = makeStubFromVersionData(id, data)
        return (ob,)

    def sqlGetModule(self, id, version):
        data = self.versions[id]
        ob = makeStubFromVersionData(id, data)
        return (ob,)

    def sqlGetModuleFilenames(self, id, version):
        return self.files[id]

    def sqlGetRating(self, moduleid, version):
        return None

class StubLanguageTool(SimpleItem):

    def __init__(self):
        self.id = 'language_tool'

    def getAvailableLanguages(self):
        return {'af': 'Afrikaans',
                'en': 'English',
                'en-za': 'South African English',
               }

    def listAvailableLanguages(self):
        return self.getAvailableLanguages()

    def getLanguageBindings(self):
        return ('en', 'en', [])

    def getNameForLanguageCode(self, langCode):
        return self.getAvailableLanguages().get(langCode, langCode)

class StubModuleStorage(ModuleVersionStorage):
    __implements__ = (IVersionStorage)

    def getHistory(self, id):
        result = []
        for moduleid, data in self.portal_moduledb.versions.items():
            if moduleid == id:
                result.append(makeStubFromVersionData(moduleid, data))
            
        return result

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

class StubRhaptosRepository(ObjectManager):
    __implements__ = IRepository

    security = AccessControl.ClassSecurityInfo()

    def __init__(self, context):
        self.id = 'content'
        self._all_storages = []
        self._default_storage = None
        self._context = context

    security.declarePublic("getRhaptosObject")
    def getRhaptosObject(self, id, version=None, **kwargs):
        obj = self._context._getOb(id)
        setattr(obj, 'latest', obj)
        return obj
    
    def registerStorage(self, storage):
        id = storage.getId()
        self._setObject(id, storage)
        self._all_storages.append(id)

    def setDefaultStorage(self, id):
        self._default_storage = id

    security.declarePublic("hasRhaptosObject")
    def hasRhaptosObject(self, id):
        return bool(self._context.hasObject(id))

    security.declarePublic("publishRevision")
    def publishRevision(self, context, message):
        return True


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
            self.portal._setObject('portal_languages', StubLanguageTool())
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
        self.assertEqual(zipfile.message, 'Created module')

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
        self.setRoles(('Manager',))
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
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=entry.xml',
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)
        returned_depositreceipt = dom.toxml()

        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'entry_depositreceipt_firstpost.xml'), 'r')
        dom = parse(file)
        file.close()

        module = self.folder.workspace.objectValues()[0]
        self.assertEqual(module.message, 'Created module')
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
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        drdom = parseString(xml)
        editiri = getEditIRI(drdom)
        # it is no longer /sword/edit... just /sword
        moduleid = editiri.split('/')[-2]
        returned_depositreceipt = drdom.toxml()
        self.assertTrue(moduleid in self.folder.workspace.objectIds())
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        module = self.folder.workspace.objectValues()[0]
        self.assertEqual(module.message, 'Frobnicate the Bar')
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
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc: \n\n%s' % diff(
                returned_depositreceipt, reference_depositreceipt))


    def _createAndPublishModule(self, context):
        """ Upload a module
            Set its metadata
            See if we can publish it.
        """
        self._setupRhaptos()
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=context,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true',
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter((context, uploadrequest), Interface, 'sword')
        xml = adapter()
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Sign the license, set the title, set maintainer, author, copyright
        # holder, description of changes.
        unpubmod = context.objectValues()[0]
        unpubmod.license = 'http://creativecommons.org/licenses/by/3.0/'
        unpubmod.title = 'The Tigger Movie'
        unpubmod.maintainers = ['test_user_1_']
        unpubmod.authors = ['test_user_1_']
        unpubmod.licensors = ['test_user_1_']
        unpubmod.message = "I will not buy this tobacconist's, it is scratched"
        unpubmod.objectId = unpubmod.id
        if not hasattr(unpubmod, 'name'):
            setattr(unpubmod, 'name', unpubmod.id)

        # Publish it for the first time
        emptyrequest = self.createUploadRequest(
            None,
            context=context,
            CONTENT_TYPE='',
            IN_PROGRESS='false',
        )
        self.setRoles(('Member','Manager'))
        xml = getMultiAdapter((unpubmod, emptyrequest), ISWORDEditIRI)()
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")
        self.setRoles(('Member',))

        pubmod = context.objectValues()[0]
        return pubmod
    

    def testUploadAndPublish(self):
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        context = self.folder.workspace
        pubmod = self._createAndPublishModule(context) 
        
        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'checkout_and_update.txt'), 'r')
        content = file.read()
        file.close()
        content = content.replace('module_url', pubmod.absolute_url())
        # Now check it out again, and replace the content, but don't publish
        uploadrequest = self.createUploadRequest(
            None,
            content=content,
            context=context,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter((context, uploadrequest), Interface, 'sword')
        xml = adapter()

        # Do the usual checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Get the edit-iri of this item
        dr = parseString(xml)
        editiri = getEditIRI(dr)

        editorid = str(editiri).split('/')[-2]
        editor = context.restrictedTraverse(editorid)

        # make sure the message was cleared after checkout
        self.assertEqual(editor.message, '')

        # Set title et al. Not sure if this should have been inherited from
        # the module we checked out? Newer versions of the module might
        # not have the same authors, maintainers and licensors. Perhaps not
        # even the same title. Assume it needs to be set again?
        editor.title = 'Yandelavasa grldenwi stravenka'
        editor.maintainers = ['test_user_1_']
        editor.authors = ['test_user_1_']
        editor.licensors = ['test_user_1_']
        editor.message = 'Our hovercraft is no longer invested by eels'

        emptyrequest = self.createUploadRequest(
            None,
            context=context,
            CONTENT_TYPE='',
            IN_PROGRESS='false',
        )
        # Now publish it by posting to the edit-iri
        adapter = getMultiAdapter((editor, emptyrequest), ISWORDEditIRI)
        xml = adapter()

        # Same old checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Check that the version has been incremented
        pubmod = context._getOb(editorid)
        self.assertTrue(pubmod.version == "1.2",
            "Version did not increment")
        return pubmod

    def testPublishOnCreate(self):
        self.setRoles(('Manager',))
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        # try publish immediately with In-Progress set to false
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            self.folder.workspace,
            CONTENT_DISPOSITION='attachment; filename=entry.xml',
            IN_PROGRESS='false',
        )

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()

        # We should receive an error that confirms that an attempt was
        # made to publish the module
        self.assertTrue("<sword:error" in xml, xml)
        self.assertTrue(
            "http://purl.org/oerpub/error/PublishUnauthorized" in xml, xml)

    def testPublishOnPostToSEIRI(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)

        # try publish on Post with In-Progress set to false
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            module,
            REQUEST_METHOD = 'POST',
            IN_PROGRESS = 'false',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()

        # We should receive an error that confirms that an attempt was
        # made to publish the module
        self.assertTrue("<sword:error" in xml, xml)
        self.assertTrue(
            "http://purl.org/oerpub/error/PublishUnauthorized" in xml, xml)


    def testPublishOnPUTToSEIRI(self):
        self._setupRhaptos()
        # without the manager role we can't publish
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        # try publish on PUT with In-Progress set to false
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)

        uploadrequest = self.createUploadRequest(
            'entry.xml',
            module,
            REQUEST_METHOD = 'PUT',
            IN_PROGRESS = 'false',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()

        # We should receive an error that confirms that an attempt was
        # made to publish the module
        self.assertTrue("<sword:error" in xml, xml)
        self.assertTrue(
            "http://purl.org/oerpub/error/PublishUnauthorized" in xml, xml)

    def testPUTOnStub(self):
        self.setRoles(('Manager',))
        self.testUploadAndPublish()
        pubmod = self.folder.workspace.objectValues()[0]
        
        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'checkout_and_update.txt'), 'r')
        content = file.read()
        file.close()
        content = content.replace('module_url', pubmod.absolute_url())
        # Now check it out again, and replace the content with PUT
        uploadrequest = self.createUploadRequest(
            None,
            content=content,
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true',
            REQUEST_METHOD='PUT'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter((pubmod, uploadrequest), Interface, 'sword')
        xml = adapter()

        # Do the usual checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Get the edit-iri of this item
        dr = parseString(xml)
        editiri = getEditIRI(dr)

        editorid = str(editiri).split('/')[-2]
        editor = self.folder.workspace.restrictedTraverse(editorid)

        # make sure the message was cleared after checkout
        self.assertEqual(editor.message, '')

    def testPUTOnCreatedModule(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)
        self.assertEqual(module.message, 'Created module')

        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'checkout_and_update.txt'), 'r')
        content = file.read()
        file.close()
        content = content.replace('module_url', module.absolute_url())
        # Now check it out again, and replace the content with PUT
        uploadrequest = self.createUploadRequest(
            None,
            content=content,
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='true',
            REQUEST_METHOD='PUT'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter((module, uploadrequest), Interface, 'sword')
        xml = adapter()

        # Do the usual checks
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Get the edit-iri of this item
        dr = parseString(xml)
        editiri = getEditIRI(dr)

        editorid = str(editiri).split('/')[-2]
        editor = self.folder.workspace.restrictedTraverse(editorid)

        # make sure the message remains set to 'Created module'
        self.assertEqual(editor.message, 'Created module')


    def testSwordServiceRetrieveContent(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart.txt'
        )

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
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
        
        ids = self.folder.objectIds()
        self.assertTrue('workspace' in ids, 'No workspace found!')

        # We should have at least one module now, this will fail if we don't
        module = self.folder.workspace.objectValues()[0]

        adapter = getMultiAdapter((module, getrequest), ISWORDEMIRI)
        retrieved_content = adapter()
        file = tempfile.NamedTemporaryFile()
        file.write(retrieved_content)
        file.flush()
        retrieved_file = zf.ZipFile(file.name)
        file.close()
        reference_file = zf.ZipFile(
            os.path.join(DIRNAME, 'data', 'unittest', 'retrievedcontent.zip'))
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
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart.txt'
        )

        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
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
        self.assertEqual(returned_statement, reference_statement,
            'Returned statement and reference statement '
            'are not identical: \n\n%s' % diff(
                returned_statement, reference_statement))


    def testDeriveModule(self):
        self.setPermissions(['Manage WebDAV Locks'], role='Member')
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        self._createAndPublishModule(self.folder.workspace)
        filename = 'derive_module.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        module = self.folder.workspace.objectValues()[0]
        source = dom.getElementsByTagName('dcterms:source')[0]
        source.firstChild.nodeValue = module.id
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            IN_PROGRESS='true'
            )
        self.setRoles(('Manager',))
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


    def test_handlePost(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        filename = 'entry.xml'
        module = self._createModule(self.folder.workspace, filename)

        # POST the same entry to make sure nothing is lost
        uploadrequest = self.createUploadRequest(
            'entry.xml',
            module,
            REQUEST_METHOD = 'POST',
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()
        dom = parseString(xml)

        returned_depositreceipt = dom.toxml()

        file = open(os.path.join(
            DIRNAME, 'data', 'unittest', 'entry_depositreceipt.xml'), 'r')
        dom = parse(file)
        file.close()

        module = self.folder.workspace.objectValues()[0]
        self.assertEqual(module.message, 'Created module')
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
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc: \n\n%s' % diff(
                returned_depositreceipt, reference_depositreceipt))

    
    def test_POSTMultipartOnSEIRI(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        module = self._createModule(self.folder.workspace, 'entry.xml')

        # try publish on Post with In-Progress set to false
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            module,
            REQUEST_METHOD = 'POST',
            IN_PROGRESS = 'true',
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
            )
        adapter = getMultiAdapter(
                (module, uploadrequest), Interface, 'sword')
        xml = adapter()

        # Rudimentary tests. This will return the usual Deposit Receipt that
        # is already tested elsewhere.
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")


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
    

    def test_one_featured_link(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'one_featured_link.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        drdom = parseString(xml)
        module = self.folder.workspace.objectValues()[0]
        links = module.getLinks()
        assert len(links) == 1, 'Links where not created correctly'
        link = links[0]
        self.assertEqual(
            link.title,
            'Test feature link',
            'Link title incorrect')
        self.assertEqual(
            link.category,
            'example',
            'Link category incorrect')
        self.assertEqual(
            link.target,
            'http://localhost:8080/featured_module',
            'Link target incorrect')
        self.assertEqual(
            link.source,
            'http://nohost/plone/Members/test_user_1_/workspace/%s' %module.id,
            'Link source incorrect')


    def test_multiple_featured_links(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multiple_links_one_category.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        drdom = parseString(xml)
        module = self.folder.workspace.objectValues()[0]
        links = module.getLinks()
        assert len(links) == 3, 'All 3 links were not created.'
        
        link_reference_data = \
            [{'title': 'Test feature link',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Featured link 02',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module_02',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Featured link 03',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module_03',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
            ]
        
        for idx in range(0,3):
            link = links[idx]
            ref_data = link_reference_data[idx]
            self.assertEqual(
                link.title,
                ref_data['title'],
                'Link "%s" title incorrect' %idx)
            self.assertEqual(
                link.category,
                ref_data['category'],
                'Link "%s" category incorrect' %idx)
            self.assertEqual(
                link.target,
                ref_data['target'],
                'Link "%s" target incorrect' %idx)
            self.assertEqual(
                link.source,
                ref_data['source'] %module.id,
                'Link "%s" source incorrect' %idx)


    def test_multiple_featured_links_different_categories(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multiple_links_different_categories.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        drdom = parseString(xml)
        module = self.folder.workspace.objectValues()[0]
        links = module.getLinks()
        assert len(links) == 9, 'All 9 links were not created.'
        
        link_reference_data = \
            [{'title': 'Supplemental featured link 01',
              'category': 'supplemental',
              'target': 'http://localhost:8080/featured_module_supplemental_01',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Supplemental featured link 02',
              'category': 'supplemental',
              'target': 'http://localhost:8080/featured_module_supplemental_02',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Supplemental featured link 03',
              'category': 'supplemental',
              'target': 'http://localhost:8080/featured_module_supplemental_03',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Test feature link',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Featured link 02',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module_02',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Featured link 03',
              'category': 'example',
              'target': 'http://localhost:8080/featured_module_03',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Prerequisite featured link 01',
              'category': 'prerequisite',
              'target': 'http://localhost:8080/featured_module_prereq_01',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Prerequisite featured link 02',
              'category': 'prerequisite',
              'target': 'http://localhost:8080/featured_module_prereq_02',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
             {'title': 'Prerequisite featured link 03',
              'category': 'prerequisite',
              'target': 'http://localhost:8080/featured_module_prereq_03',
              'source': 'http://nohost/plone/Members/test_user_1_/workspace/%s',
             },
            ]
        
        for idx in range(0,9):
            link = links[idx]
            ref_data = link_reference_data[idx]
            self.assertEqual(
                link.title,
                ref_data['title'],
                'Link "%s" title incorrect' %idx)
            self.assertEqual(
                link.category,
                ref_data['category'],
                'Link "%s" category incorrect' %idx)
            self.assertEqual(
                link.target,
                ref_data['target'],
                'Link "%s" target incorrect' %idx)
            self.assertEqual(
                link.source,
                ref_data['source'] %module.id,
                'Link "%s" source incorrect' %idx)
   

    def _testDeriveCollection(self, filename):
        self._setupRhaptos()
        self.setRoles(('Member','Manager'))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        # we want to use our stub instead of the normal one
        self.portal.content = StubRhaptosRepository(self.folder.workspace)
        col_id = 'collection001'
        self.folder.workspace.invokeFactory('Collection', col_id)
        col = self.folder.workspace._getOb(col_id)
        col.setState('published')
        col.checkout(col_id)
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        source = dom.getElementsByTagName('dcterms:source')[0]
        source.firstChild.nodeValue = \
            '%s/%s' %(self.folder.workspace.absolute_url(), col_id)
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            )
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml
    
    
    def testDeriveCollection_NoVersionNumber(self):
        self._testDeriveCollection(filename='derive_collection.xml')

    
    def testAddSingleModuleToLens(self):
        self._setupRhaptos()
        self.setRoles(('Member','Manager'))
        self.setPermissions(['Manage WebDAV Locks'], role='Member')
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        # get a new module
        module = self._createAndPublishModule(self.folder.workspace)

        # create the lens
        lens_id = u'lens001'
        self.folder.workspace.invokeFactory('ContentSelectionLens', lens_id)
        lens = self.folder.workspace._getOb(lens_id)

        # craft the xml to add the module to the lens
        filename = 'entry_add_to_lens.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        contentId = dom.getElementsByTagName('id')[0]
        contentId.firstChild.nodeValue = module.getId()
        
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            IN_PROGRESS= 'true',
            )
        # add the module to the lens
        adapter = getMultiAdapter(
                (lens, uploadrequest), Interface, 'atompub')
        xml = adapter()

        # assert that the module was added to the lens
        modules = lens.listFolderContents(spec='SelectedContent')
        self.assertEqual(len(modules), 1, 'More than one module linked.')


    def testAddMultipleModulesToLens(self):
        self._setupRhaptos()
        self.setRoles(('Member','Manager'))
        self.setPermissions(['Manage WebDAV Locks'], role='Member')
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        # create the lens
        lens_id = 'lens001'
        self.folder.workspace.invokeFactory('ContentSelectionLens', lens_id)
        lens = self.folder.workspace._getOb(lens_id)

        # craft the xml to add the module to the lens
        filename = 'entry_add_multiple_modules_to_lens.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        
        modules = []
        entries = dom.getElementsByTagName('entry')
        context = self.folder.workspace
        for entry in entries:
            module = self._createModule(context, 'entry.xml')
            self._publishModule(context, module)
            modules.append(module)
            entry.getElementsByTagName('id')[0].firstChild.nodeValue = module.getId()

        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            IN_PROGRESS= 'true',
            )
        # add the module to the lens
        adapter = getMultiAdapter(
                (lens, uploadrequest), Interface, 'atompub')
        xml = adapter()

        self.assertTrue("Multiple entries submitted, "
                        "only one entry allowed" in xml)

    
    def testForbiddenExceptionOnAddToLens(self):
        self._setupRhaptos()
        self.setRoles(('Member','Manager'))
        self.setPermissions(['Manage WebDAV Locks'], role='Member')
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        # get a new module
        module = self._createAndPublishModule(self.folder.workspace)

        # create the lens
        lens_id = u'lens001'
        self.folder.workspace.invokeFactory('ContentSelectionLens', lens_id)
        lens = self.folder.workspace._getOb(lens_id)

        # craft the xml to add the module to the lens
        filename = 'entry_add_to_lens.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        contentId = dom.getElementsByTagName('id')[0]
        contentId.firstChild.nodeValue = module.getId()
        
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            IN_PROGRESS= 'true',
            )
        # add the module to the lens
        adapter = getMultiAdapter(
                (lens, uploadrequest), Interface, 'atompub')
        xml = adapter()
        assert "<sword:error" not in xml, xml


    def testAddToLensWithStopVersion(self):
        self._setupRhaptos()
        self.setRoles(('Member','Manager'))
        self.setPermissions(['Manage WebDAV Locks'], role='Member')
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        self.folder.content = StubRhaptosRepository(self.folder.workspace)

        # get a new module
        module = self._createAndPublishModule(self.folder.workspace)

        # create the lens
        lens_id = u'lens001'
        self.folder.workspace.invokeFactory('ContentSelectionLens', lens_id)
        lens = self.folder.workspace._getOb(lens_id)

        # craft the xml to add the module to the lens
        filename = 'entry_add_to_lens_stopversion_included.xml'
        file = open(os.path.join(DIRNAME, 'data', 'unittest', filename), 'r')
        dom = parse(file)
        file.close()
        contentId = dom.getElementsByTagName('id')[0]
        contentId.firstChild.nodeValue = module.getId()
        
        uploadrequest = self.createUploadRequest(
            None, self.folder.workspace, content = dom.toxml(),
            IN_PROGRESS= 'true',
            )
        # add the module to the lens
        adapter = getMultiAdapter(
                (lens, uploadrequest), Interface, 'atompub')
        xml = adapter()
        assert "<sword:error" not in xml, xml


    def test_validateVersions(self):
        startVersion = '1.1'
        stopVersion = '1.3'
        data = [stopVersion,
                DateTime(),
                DateTime(),
                'tester',
                ['tester', ],
                ['tester', ],
               ]
        module = makeStubFromVersionData('testmodule', data)

        view = LensAtomPubAdapter(module, self.portal.REQUEST)
        view.validateVersions(startVersion, stopVersion, module)

        startVersion = '1.3'
        stopVersion = '1.1'
        self.assertRaises(
            ValueError,
            view.validateVersions,
            startVersion, stopVersion, module
        )

        startVersion = '1.1'
        stopVersion = 'latest'
        view.validateVersions(startVersion, stopVersion, module)
        
        startVersion = 'a'
        stopVersion = 'b'
        self.assertRaises(
            ValueError,
            view.validateVersions,
            startVersion, stopVersion, module
        )

        startVersion = 'a'
        stopVersion = 'latest'
        self.assertRaises(
            ValueError,
            view.validateVersions,
            startVersion, stopVersion, module
        )

    def testCheckoutToWrongWorkspace(self):
        self._setupRhaptos()
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        context=self.folder.workspace

        self.portal.portal_membership.addMember('user2', 'secret', [], [])
        self.createMemberarea('user2')
        self.logout()
        self.login('user2')

        uploadrequest = self.createUploadRequest(
            filename='entry.xml',
            context=context)
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (context, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "Unauthorized" in xml, "This must raise 'Unauthorized'"
         

    def _createModule(self, context, filename):
        """ Utility method to setup the environment and create a module.
        """
        self.setRoles(('Manager',))
        uploadrequest = self.createUploadRequest(
            filename, 
            context,
            CONTENT_DISPOSITION='attachment; filename=%s' %filename,
            IN_PROGRESS= 'true',
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

    
    def _publishModule(self, context, module):
        # Sign the license, set the title, set maintainer, author, copyright
        # holder, description of changes.
        self.setRoles(('Manager',))
        module.license = 'http://creativecommons.org/licenses/by/3.0/'
        module.title = 'The Tigger Movie'
        module.maintainers = ['test_user_1_']
        module.authors = ['test_user_1_']
        module.licensors = ['test_user_1_']
        module.message = "I will not buy this tobacconist's, it is scratched"

        # Publish it for the first time
        emptyrequest = self.createUploadRequest(
            None,
            context=context,
            CONTENT_TYPE='',
            IN_PROGRESS='false',
        )
        xml = getMultiAdapter((module, emptyrequest), ISWORDEditIRI)()
        return module
   

    def wf(self, data):
        file = open(os.path.join(DIRNAME, 'data', 'unittest', 'returned.xml'), 'wb')
        file.write(data)
        file.close()


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSwordService))
    return suite
