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
        env = {
            'CONTENT_TYPE': 'application/zip',
            'CONTENT_LENGTH': len(ZIPFILE),
            'CONTENT_DISPOSITION': 'attachment; filename=perry.zip',
            'REQUEST_METHOD': 'POST',
            'SERVER_NAME': 'nohost',
            'SERVER_PORT': '80'
        }
        uploadresponse = HTTPResponse(stdout=StringIO())
        uploadrequest = clone_request(self.app.REQUEST, uploadresponse, env)
        uploadrequest.set('BODYFILE', StringIO(decodestring(ZIPFILE)))
        # Fake PARENTS
        uploadrequest.set('PARENTS', [self.folder])

        # Call the sword view on this request to perform the upload
        self.setRoles(('Manager',))
        xml = getMultiAdapter(
            (self.folder, uploadrequest), Interface, 'sword')()
        assert bool(xml), "Upload view does not return a result"
        assert "<sword:error" not in xml, xml

        # Test that we can still reach the edit-iri
        assert self.folder.restrictedTraverse('perry.zip/sword/edit')


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

# base64 representation of a small test zip file
ZIPFILE="""\
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
AAAAAAAAAAAAADEzMTMwNjM1MjNfbTExODY4XzEtNi16aXAvaW5kZXguY254bWxQSwECFAAUAAAA
CAAycAs/3M0VlFAJAAAeHQAANAAAAAAAAAAAAAAAAADvCAAAMTMxMzA2MzUyM19tMTE4NjhfMS02
LXppcC9pbmRleF9hdXRvX2dlbmVyYXRlZC5jbnhtbFBLAQIUABQAAAAIADJwCz/rN/BMXAIAAM4C
AAAnAAAAAAAAAAAAAAAAAJESAAAxMzEzMDYzNTIzX20xMTg2OF8xLTYtemlwL2hfYWxscGFzcy5w
bmdQSwECFAAUAAAACAAycAs/bYUOP/YCAAArAwAAJwAAAAAAAAAAAAAAAAAyFQAAMTMxMzA2MzUy
M19tMTE4NjhfMS02LXppcC9oX2xvd3Bhc3MucG5nUEsBAhQAFAAAAAgAMnALPxCV5vy7AwAABAQA
ACgAAAAAAAAAAAAAAAAAbRgAADEzMTMwNjM1MjNfbTExODY4XzEtNi16aXAvaF9iYW5kc3RvcC5w
bmdQSwECFAAUAAAACAAycAs/KrH8pnADAACoAwAAKAAAAAAAAAAAAAAAAABuHAAAMTMxMzA2MzUy
M19tMTE4NjhfMS02LXppcC9oX2JhbmRwYXNzLnBuZ1BLAQIUABQAAAAIADJwCz8Eg11/DAIAANgJ
AAAoAAAAAAAAAAAAAAAAACQgAAAxMzEzMDYzNTIzX20xMTg2OF8xLTYtemlwL2lkZWFsRmlsdGVy
cy5tUEsBAhQAFAAAAAgAMnALP626MJvwAgAANAMAACgAAAAAAAAAAAAAAAAAdiIAADEzMTMwNjM1
MjNfbTExODY4XzEtNi16aXAvaF9oaWdocGFzcy5wbmdQSwECFAAUAAAACAAycAs/R6IihR4BAAAm
AgAAJwAAAAAAAAAAAAAAAACsJQAAMTMxMzA2MzUyM19tMTE4NjhfMS02LXppcC9ub3RjaEZpbHRl
ci5tUEsBAhQAFAAAAAgAMnALP1/n/qAUBQAAegUAACUAAAAAAAAAAAAAAAAADycAADEzMTMwNjM1
MjNfbTExODY4XzEtNi16aXAvaF9ub3RjaC5wbmdQSwECFAAUAAAACAAycAs/QS4LzJsIAACFGQAA
LQAAAAAAAAAAAAAAAABmLAAAMTMxMzA2MzUyM19tMTE4NjhfMS02LXppcC9pbmRleC5jbnhtbC5w
cmUtdjA3UEsFBgAAAAALAAsAugMAAEw1AAAAAA==\
"""
