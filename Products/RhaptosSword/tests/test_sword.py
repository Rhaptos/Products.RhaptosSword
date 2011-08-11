import os, sys
if __name__ == '__main__':
    execfile(os.path.join(sys.path[0], 'framework.py'))

from StringIO import StringIO
from base64 import decodestring
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import getAdapter, getMultiAdapter
from zope.publisher.interfaces import IPublishTraverse
from zope.interface import Interface, directlyProvides, directlyProvidedBy
from Acquisition import aq_base
from ZPublisher.HTTPRequest import HTTPRequest
from ZPublisher.HTTPResponse import HTTPResponse
from Products.Five import BrowserView
from Products.CMFCore.interfaces import IFolderish

from Products.PloneTestCase import PloneTestCase

from rhaptos.swordservice.plone.browser.sword import ISWORDService
from rhaptos.swordservice.plone.browser.sword import ServiceDocument

from Testing import ZopeTestCase
ZopeTestCase.installProduct('RhaptosSword')
ZopeTestCase.installProduct('RhaptosModuleEditor')
ZopeTestCase.installProduct('RhaptosRepository')
ZopeTestCase.installProduct('CNXMLDocument')

PloneTestCase.setupPloneSite()

#PloneTestCase.setupPloneSite(extension_profiles=['Products.RhaptosModuleEditor',])
# setupPloneSite accepts an optional products argument, which allows you to
# specify a list of products that will be added to the portal using the
# quickinstaller tool. Since 0.8.2 you can also pass an extension_profiles
# argument to import GS extension profiles.

DIRNAME = os.path.dirname(__file__)

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
        request = self.portal.REQUEST

        # Check that 'sword' ends up at a browser view
        view = self.portal.restrictedTraverse('sword')
        assert isinstance(view, BrowserView)

        # Test service-document
        view = self.portal.restrictedTraverse('sword/servicedocument')
        assert isinstance(view, ServiceDocument)
        assert "<sword:error" not in view()

        # Upload a zip file
        zipfilename = os.path.join(DIRNAME, 'data', 'm11868_1.6.zip')
        zipfile = open(zipfilename, 'r')
        env = {
            'CONTENT_TYPE': 'application/zip',
            'CONTENT_LENGTH': os.path.getsize(zipfilename),
            'CONTENT_DISPOSITION': 'attachment; filename=perry.zip',
            'REQUEST_METHOD': 'POST',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80'
        }
        uploadresponse = HTTPResponse(stdout=StringIO())
        uploadrequest = clone_request(self.app.REQUEST, uploadresponse, env)
        uploadrequest.set('BODYFILE', zipfile)
        # Fake PARENTS
        uploadrequest.set('PARENTS', [self.folder])

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        xml = getMultiAdapter(
            (self.folder, uploadrequest), Interface, 'sword')()
        zipfile.close()
        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml

        # Test that we can still reach the edit-iri
        assert self.folder.restrictedTraverse('perry.zip/sword/edit')


    def testFoldersAreFolderish(self):
        self.assertTrue(IFolderish.providedBy(self.folder), "Folders are not Folderish")


    def testMetadata(self):
        """http://localhost:8080/Members/admin/@@sword"""
        # XXX: the next 3 lines need to move to afterSetup but
        # afterSetup is not being called for some reason
        self.addProduct('RhaptosSword')
        self.addProfile('Products.RhaptosModuleEditor:default')
        self.addProfile('Products.CNXMLDocument:default')
        self.portal.manage_addProduct['CMFPlone'].addPloneFolder('workspace') 
        self.portal.manage_addProduct['RhaptosRepository'].manage_addRepository('content') 
        self.portal._setObject('portal_moduledb', StubModuleDB())
        self.portal._setObject('portal_languages', StubLanuageTool())

        xml = os.path.join(DIRNAME, 'data', 'entry.xml')
        file = open(xml, 'rb')
        content = file.read()
        file.close()
        # Upload a zip file
        env = {
            'CONTENT_TYPE': 'application/atom+xml;type=entry',
            'CONTENT_LENGTH': len(content),
            'IN-PROGRESS': 'True',
            'REQUEST_METHOD': 'POST',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80'
        }
        uploadresponse = HTTPResponse(stdout=StringIO())
        uploadrequest = clone_request(self.app.REQUEST, uploadresponse, env)
        uploadrequest.set('BODYFILE', StringIO(content))
        # Fake PARENTS
        uploadrequest.set('PARENTS', [self.portal.workspace])

        # Call the sword view on this request to perform the upload
        xml = getMultiAdapter(
            (self.portal.workspace, uploadrequest), Interface, 'sword')()
        

        assert "<sword:error" not in xml, xml

        # Test that we can reach the edit-iri
        # TODO: will have to open the recceipt and use the edit iri returned.


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestSwordService))
    return suite
