from DateTime import DateTime
from xml.dom.minidom import parse

from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, getMultiAdapter, queryAdapter, queryUtility
from webdav.NullResource import NullResource

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 


class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


def validateLicense(context, license_url):
    """
    We try to lookup the license details based on the url.
    If we don't have this license in the database, it will raise an
    exception. The whole process should stop at that point.
    """
    mdt = getToolByName(context, 'portal_moduledb')
    mdt.getLicenseData(license_url)
    return license_url



class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)
    
    METADATA_MAPPING =\
            {'title'   : 'title',
             'keywords': 'keywords',
             'abstract': 'abstract',
             'language': 'language',
             'subject' : 'subject',
             'license' : 'license',
             'googleAnalyticsTrackingCode': 'GoogleAnalyticsTrackingCode',
            }
    
    VALIDATORS =\
            {'license': validateLicense,}


    def updateObject(self, obj, filename, request, response, content_type):
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)

            obj = obj.__of__(self.context)
            metadata = self.getMetadata(dom, self.METADATA_MAPPING)
            obj.update_metadata(**metadata)
            obj.reindexObject(idxs=metadata.keys())
        return obj


    def getMetadata(self, dom, mapping):
        headers = self.getHeaders(dom, mapping)
        metadata = {}
        for key, value in headers:
            if key == 'license':
                value = validateLicense(self.context, value)
            if value: metadata[key] = value
        return metadata
