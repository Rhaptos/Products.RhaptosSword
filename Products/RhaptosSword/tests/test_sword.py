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

from Products.PloneTestCase import PloneTestCase

from rhaptos.swordservice.plone.browser.sword import ISWORDService
from rhaptos.swordservice.plone.browser.sword import ServiceDocument
from Products.RhaptosRepository.interfaces.IVersionStorage import IVersionStorage

from Testing import ZopeTestCase
ZopeTestCase.installProduct('RhaptosSword')
ZopeTestCase.installProduct('RhaptosModuleEditor')
ZopeTestCase.installProduct('RhaptosRepository')
ZopeTestCase.installProduct('CNXMLDocument')
ZopeTestCase.installProduct('UniFile')

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

class StubZRDBResult(object):
    def tuples(self):
        return [(1, 'Arts', 'ISKME subject'),
                (2, 'Business', 'ISKME subject'),
                (3, 'Humanities', 'ISKME subject'),
                (4, 'Mathematics and Statistics', 'ISKME subject'),
                (5, 'Science and Technology', 'ISKME subject'),
                (6, 'Social Sciences', 'ISKME subject')
               ]

class StubModuleDB(SimpleItem):

    def __init__(self):
        self.id = 'portal_moduledb'

    def getLicenseData(self, url):
        return True

    def sqlGetTags(self, scheme):
        return StubZRDBResult()

class StubLanuageTool(SimpleItem):

    def __init__(self):
        self.id = 'language_tool'

    def getAvailableLanguages(self):
        return {'en': 'English'}

    def getLanguageBindings(self):
        return ('en', 'en', [])

class StubStorage(SimpleItem):
    __implements__ = (IVersionStorage)

    def __init__(self, id):
        self.id = id
        self.latest = {}

    def getId(self):
        return self.id

    def isUnderVersionControl(self, object):
        return getattr(object.aq_base, 'objectId', None) is not None

    def applyVersionControl(self, object):
        if self.isUnderVersionControl(object):
            raise ValueError, "Already under version control"
        repo = self.aq_parent
        count = len(repo.objectIds())-2 # ignore storage and cache
        object.objectId = 'm%d' % (10001+count)
        return object.objectId

    def createVersionFolder(self, object):
        folder = PortalFolder(object.objectId)
        self.aq_parent._setObject(object.objectId, folder)

    def checkinResource(self, object, message='', user=None):
        vf = self.aq_parent._getOb(object.objectId)
        minor = len(vf.objectIds())
        object.version = "1.%d" % minor
        object.revised = DateTime()
        object.submitter = user
        object.submitlog = message
        vf._setObject(object.objectId, object)
        self.latest[object.objectId] = object

    def getObject(self, id, version=None, **kw):
        if version is None or version == 'latest':
            return self.latest[id]
        vf = self.aq_parent._getOb(id)
        return vf._getOb(version)

    def notifyObjectRevised(self, object, origobj=None):
        pass


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

class TestSwordService(PloneTestCase.PloneTestCase):
    def afterSetup(self):
        pass


    def testSwordService(self):
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
        uploadrequest.set('PARENTS', [self.folder])

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        adapter = getMultiAdapter(
            (self.folder, uploadrequest), Interface, 'sword')
        xml = adapter()
        zipfile.close()
        # Test that we can still reach the edit-iri
        assert self.folder.restrictedTraverse('m11868_1-6.zip/sword/edit')
        zipfile = self.folder._getOb('m11868_1-6.zip')

        file = open(os.path.join(DIRNAME, 'data', 'depositreceipt_plain_zipfile.xml'), 'r')
        dom = parse(file)
        file.close()
        dates = dom.getElementsByTagName('updated')
        dates[0].firstChild.nodeValue = zipfile.modified()
        reference_depositreceipt = dom.toxml()
        returned_depositreceipt = parseString(xml).toxml()
        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml
        self.assertEqual(returned_depositreceipt, reference_depositreceipt,
            'Result does not match reference doc')


    def testFoldersAreFolderish(self):
        self.assertTrue(IFolderish.providedBy(self.folder), "Folders are not Folderish")


    def createUploadRequest(self, filename, context, **kwargs):
        # XXX: This method needs to move to afterSetup, but afterSetup is not
        # being called for some reason.
        self.addProduct('RhaptosSword')
        self.addProfile('Products.RhaptosModuleEditor:default')
        self.addProfile('Products.CNXMLDocument:default')
        self.addProfile('Products.CNXMLTransforms:default')
        self.addProfile('Products.UniFile:default')
        objectIds = self.portal.objectIds()
        if not 'content' in objectIds:
            self.portal.manage_addProduct['RhaptosRepository'].manage_addRepository('content') 
            # We need storage for our published modules. This is as good a place as
            # any.
            self.portal.content.registerStorage(StubStorage('bar'))
            self.portal.content.setDefaultStorage('bar')
        if not 'portal_moduledb' in objectIds:
            self.portal._setObject('portal_moduledb', StubModuleDB())
        if not 'portal_languages' in objectIds:
            self.portal._setObject('portal_languages', StubLanuageTool())

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


    def _test_publishBadAtomXML(self):
        """
         See what happens when we throw bad xml at the import funtionality.
        """
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest('bad_entry.xml', self.portal.workspace)

        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        self.failUnlessRaises(ExpatError, view)


    def testMetadata(self):
        """ See if the metadata is added correctly. """
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
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            SLUG='multipart'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        returned_depositreceipt = parseString(xml).toxml()
        self.assertTrue("multipart" in self.portal.workspace.objectIds())
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
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            IN_PROGRESS='false',
            SLUG='multipart',
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()
        # Unfortunately none of this works because we are unauthorised to
        # publish from a unit test. publishContent.cpy hates us.
        self.assertTrue("<sword:error" not in xml, xml)
        self.assertTrue("multipart" in self.portal.workspace.objectIds())
        self.assertTrue(
            self.portal.workspace._getOb('multipart').state == 'published',
            "Did not publish")
        self.assertTrue("<entry" in xml, "Not a valid deposit receipt")
        

    def testCheckoutAndUpdate(self):
        # This test does not work because we are unable to create published
        # modules in unit tests, and so we have nothing to check out.
        uploadrequest = self.createUploadRequest(
            'checkout_and_update.xml',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            SLUG='multipart'
        )
        # Call the sword view on this request to perform the upload
        adapter = getMultiAdapter(
                (self.portal.workspace, uploadrequest), Interface, 'sword')
        xml = adapter()


    def testSwordServiceRetrieveContent(self):
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.portal.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            SLUG='multipart',
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
        self.setRoles(('Manager',))
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        uploadrequest = self.createUploadRequest('entry.xml', self.portal.workspace)
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

        dom = parseString(xml)
        edit_iri = module.absolute_url() + '/sword/edit'
        edit_media_iri = module.absolute_url()
        statement_iri = module.absolute_url() + '/sword/statement'
        links = dom.getElementsByTagName('link')
        for link in links:
            rel = str(link.attributes['rel'].value)
            href = str(link.attributes['href'].value)
            if rel == 'edit':
                self.assertEqual(href,
                    edit_iri, 'Edit IRI is incorrect.')
            elif rel == 'edit-media':
                self.assertEqual(href,
                    edit_media_iri, 'Media IRI is incorrect.')
            elif rel == 'http://purl.org/net/sword/terms/add':
                self.assertEqual(href,
                    edit_iri, 'Termas add IRI is incorrect.')
            elif rel == 'http://purl.org/net/sword/terms/statement':
                self.assertEqual(href,
                    statement_iri, 'Statement IRI is incorrect.')
            elif rel == 'http://purl.org/net/sword/terms/originalDeposit':
                self.assertEqual(href,
                    module.absolute_url(), 'Original deposit IRI is incorrect.')

        state = dom.getElementsByTagNameNS('http://purl.org/net/sword/', 'state')
        self.failUnless(len(state) > 0)
        href = str(state[0].attributes['href'].value)
        self.assertEqual(href, module.absolute_url(), 'State IRI is incorrect.')

        state_description = dom.getElementsByTagNameNS(
            'http://purl.org/net/sword/', 'stateDescription')
        self.failUnless(len(state_description) > 0)
        paragraphs = state_description[0].getElementsByTagName('p')
        value = str(paragraphs[1].firstChild.nodeValue)
        self.assertEqual(value, 'created', 'State mismatch.')

        orig_deposit = dom.getElementsByTagNameNS(
            'http://purl.org/net/sword/', 'originalDeposit')
        self.failUnless(len(orig_deposit) > 0) 
        href = str(orig_deposit[0].attributes['href'].value)
        self.assertEqual(href, module.absolute_url(),
            'Original deposit IRI is incorrect.')

        packaging = orig_deposit[0].getElementsByTagNameNS(
            'http://purl.org/net/sword/', 'packaging')
        self.failUnless(len(packaging) > 0) 
        value = str(packaging[0].firstChild.nodeValue)
        self.assertEqual(value, 'application/xhtml+xml',
            'Packinging incorrect.')

        deposited_on = orig_deposit[0].getElementsByTagNameNS(
            'http://purl.org/net/sword/', 'depositedOn')
        self.failUnless(len(deposited_on) > 0) 
        value = str(deposited_on[0].firstChild.nodeValue)
        created = DateTime(value)
        self.assertEqual(created.year(), now.year(), 'Year mismatch.')
        self.assertEqual(created.month(), now.month(), 'Month mismatch.')
        self.assertEqual(created.day(), now.day(), 'Day mismatch.')
        self.assertEqual(created.hour(), now.hour(), 'Hour mismatch.')
        self.assertEqual(created.minute(), now.minute(), 'Minute mismatch.')
        self.assertEqual(created.second(), now.second(), 'Second mismatch.')


    def testDeriveModule(self):
        self.setRoles(('Manager',))
        self.folder.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 

        uploadrequest = self.createUploadRequest(
            'multipart.txt',
            context=self.folder.workspace,
            CONTENT_TYPE='multipart/related; boundary="===============1338623209=="',
            SLUG='multipart',
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
    

    def writecontents(self, contents, filename):
        file = open(os.path.join(DIRNAME, 'data', filename), 'w')
        file.write(contents)
        file.close()


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSwordService))
    return suite
