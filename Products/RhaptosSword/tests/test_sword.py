import os, sys
if __name__ == '__main__':
    execfile(os.path.join(sys.path[0], 'framework.py'))

import zipfile as zf
import tempfile
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

from Products.PloneTestCase import PloneTestCase

from rhaptos.swordservice.plone.browser.sword import ISWORDService
from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
from Products.RhaptosSword.browser.views import ServiceDocument
from Products.RhaptosRepository.interfaces.IVersionStorage import IVersionStorage
from Products.RhaptosRepository.VersionFolder import incrementMinor
from Products.RhaptosModuleStorage.ModuleVersionFolder import ModuleVersionStorage
from Products.RhaptosModuleStorage.ModuleDBTool import CommitError
from Products.RhaptosModuleStorage.ModuleView import ModuleView
from Products.RhaptosCollaborationTool.interfaces.portal_collaboration import portal_collaboration as ICollaborationTool

from Testing import ZopeTestCase
ZopeTestCase.installProduct('RhaptosSword')
ZopeTestCase.installProduct('RhaptosModuleEditor')
ZopeTestCase.installProduct('RhaptosRepository')
ZopeTestCase.installProduct('CNXMLDocument')
ZopeTestCase.installProduct('UniFile')
ZopeTestCase.installProduct('RhaptosCollaborationTool')

PloneTestCase.setupPloneSite()

#PloneTestCase.setupPloneSite(extension_profiles=['Products.RhaptosModuleEditor',])
# setupPloneSite accepts an optional products argument, which allows you to
# specify a list of products that will be added to the portal using the
# quickinstaller tool. Since 0.8.2 you can also pass an extension_profiles
# argument to import GS extension profiles.

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
        return {'en': 'English'}

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
        self.wgs = [{'link': 'http://link.example.com',
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

class TestSwordService(PloneTestCase.PloneTestCase):
    def afterSetup(self):
        pass


    def _setupRhaptos(self):
        # XXX: This method needs to move to afterSetup, but afterSetup is not
        # being called for some reason.
        self.addProduct('RhaptosSword')
        self.addProfile('Products.RhaptosModuleEditor:default')
        self.addProfile('Products.CNXMLDocument:default')
        self.addProfile('Products.CNXMLTransforms:default')
        self.addProfile('Products.UniFile:default')
        self.addProfile('Products.LinkMapTool:default')
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
            content = ''
        else:
            xml = os.path.join(DIRNAME, 'data', filename)
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
        file = open(os.path.join(DIRNAME, 'data', 'servicedocument.xml'), 'r')
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

        # Upload a zip file, but don't publish
        zipfilename = os.path.join(DIRNAME, 'data', 'm11868_1.6.zip')
        zipfile = open(zipfilename, 'r')
        env = {
            'CONTENT_TYPE': 'application/zip',
            'CONTENT_LENGTH': os.path.getsize(zipfilename),
            'CONTENT_DISPOSITION': 'attachment; filename=m11868_1.6.zip',
            'REQUEST_METHOD': 'POST',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80',
            'IN_PROGRESS': 'true',
        }
        uploadresponse = HTTPResponse(stdout=StringIO())
        uploadrequest = clone_request(self.app.REQUEST, uploadresponse, env)
        uploadrequest.set('BODYFILE', zipfile)
        # Fake PARENTS
        uploadrequest.set('PARENTS', [self.portal.workspace])

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        adapter = getMultiAdapter(
            (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        zipfile.close()

        # There should be no errors
        self.assertTrue("<sword:error" not in xml, xml)

        # Test that we can still reach the edit-iri
        drdom = parseString(xml)
        editiri = str(getEditIRI(drdom))
        moduleid = editiri.split('/')[-3]
        self.assertTrue(bool(
            self.portal.workspace.restrictedTraverse('%s/sword/edit' % moduleid)),
            "Cannot access deposit receipt")
        zipfile = self.portal.workspace._getOb(moduleid)

        file = open(os.path.join(DIRNAME, 'data', 'depositreceipt_plain_zipfile.xml'), 'r')
        dom = parse(file)
        file.close()
        dates = dom.getElementsByTagName('updated')
        dates[0].firstChild.nodeValue = zipfile.modified()
        reference_depositreceipt = dom.toxml()
        returned_depositreceipt = parseString(xml).toxml()
        self.assertTrue(bool(xml), "Upload view does not return a result")
        # FIXME: This is probably the wrong way to check the deposit receipt.
        # rather check programatically that everything that must be there is
        # there.
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc')


    def testFoldersAreFolderish(self):
        self.assertTrue(IFolderish.providedBy(self.folder), "Folders are not Folderish")


    def test_publishBadAtomXML(self):
        """
         See what happens when we throw bad xml at the import funtionality.
        """
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest('bad_entry.xml', self.portal.workspace)

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        self.failUnlessRaises(ExpatError, view)


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

        file = open(os.path.join(DIRNAME, 'data', 'entry_depositreceipt.xml'), 'r')
        dom = parse(file)
        file.close()
        dates = dom.getElementsByTagName('updated')
        module = self.portal.workspace.objectValues()[0]
        dates[0].firstChild.nodeValue = module.revised
        created = dom.getElementsByTagName('dcterms:created')
        for element in created:
            element.firstChild.nodeValue = module.created
        modified = dom.getElementsByTagName('dcterms:modified')
        for element in modified:
            element.firstChild.nodeValue = module.revised
        reference_depositreceipt = dom.toxml()

        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc')


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
        moduleid = editiri.split('/')[-3]
        returned_depositreceipt = drdom.toxml()
        self.assertTrue(moduleid in self.portal.workspace.objectIds())
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        module = self.portal.workspace.objectValues()[0]
        file = open(os.path.join(DIRNAME, 'data', 'multipart_depositreceipt.xml'), 'r')
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
        reference_depositreceipt = dom.toxml()

        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc')

    def testUploadAndPublish(self):
        self._setupRhaptos()
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='false',
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        # We don't really need to be Manager, but I'll be damned if I'm
        # debugging a permissions issue that only happens when we test. I
        # already wasted too much time on this. If you know better, please fix
        # it. The problem is that publishContent.cpy is not allowed to call
        # manage_renameObjects, although its perfectly fine if you do it
        # from here, and we even have the Owner role on both the module and the
        # workspace. Probably something to do with trusted code and what not.
        self.setRoles(('Member', 'Manager'))
        xml = adapter()
        self.setRoles(('Member',))
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("m10001" in self.portal.workspace.objectIds())
        pubmod = self.portal.workspace._getOb('m10001')
        self.assertTrue(pubmod.state == 'published', "Did not publish")
        self.assertTrue(pubmod.version == "1.1",
            "First published is not version 1.1")
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")

        # Now check it out again, and replace the content, but don't publish
        uploadrequest = self.createUploadRequest(
            'checkout_and_update.txt',
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
        editorid = str(editiri).split('/')[-3]
        editor = self.portal.workspace.restrictedTraverse(editorid)

        # Now publish it by posting to the edit-iri
        uploadrequest = self.createUploadRequest(
            None,
            context=self.portal.workspace,
            CONTENT_TYPE='text/plain',
            IN_PROGRESS='false',
        )
        adapter = getMultiAdapter((editor, uploadrequest), ISWORDEditIRI)
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

        adapter = getMultiAdapter(
            (module, getrequest), Interface, 'sword')
        retrieved_content = adapter()
        file = tempfile.NamedTemporaryFile()
        file.write(retrieved_content)
        file.flush()
        retrieved_file = zf.ZipFile(file.name)
        file.close()
        reference_file = zf.ZipFile(
            os.path.join(DIRNAME, 'data', 'retrievedcontent.zip'))
        self.assertEqual(retrieved_file.namelist(), reference_file.namelist(),
            'The files are not the same.')

    
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
        view = module.restrictedTraverse('sword/statement')
        xml = view()
        assert "<sword:error" not in xml, xml
        returned_statement = parseString(xml).toxml()

        file = open(os.path.join(DIRNAME, 'data', 'multipart_statement.xml'), 'r')
        dom = parse(file)
        file.close()
        reference_statement = dom.toxml()
        self.assertEqual(returned_statement, reference_statement,
            'Returned statement and reference statement are not identical.')


    def testDeriveModule(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart')
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml

        uploadrequest = self.createUploadRequest('derive_module.xml', self.folder.workspace)
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml


    def test_handlePUT(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            CONTENT_DISPOSITION='attachment; filename=multipart')
        adapter = getMultiAdapter(
                (self.folder.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        assert "<sword:error" not in xml, xml

        uploadrequest = self.createUploadRequest(
                'test3_atom_entry.xml',
            self.folder.workspace,
            REQUEST_METHOD = 'PUT',
            )
        module = self.folder.workspace.objectValues()[0]
        adapter = getMultiAdapter((module, uploadrequest), ISWORDEditIRI)
        xml = adapter()

    
    def test_addRoles(self):
        self._setupRhaptos()
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        module = self._createModule(self.folder.workspace, 'test_roles.xml')
    

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

        module = context.objectValues()[0]
        return module


    def writecontents(self, contents, filename):
        file = open(os.path.join(DIRNAME, 'data', filename), 'w')
        file.write(contents)
        file.close()


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSwordService))
    return suite
