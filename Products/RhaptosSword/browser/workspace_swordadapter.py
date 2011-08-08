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


METADATA_MAPPING =\
        {'title'   : 'title',
         'keywords': 'keywords',
         'abstract': 'abstract',
         'language': 'language',
         'subject' : 'subject',
         'license' : 'license',
         'googleAnalyticsTrackingCode': 'GoogleAnalyticsTrackingCode',
        }


class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)
    
    def updateObject(self, obj, filename, request, response, content_type):
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)

            obj = obj.__of__(self.context)
            metadata = self.getMetadata(dom, METADATA_MAPPING)
            obj.update_metadata(**metadata)
            obj.reindexObject(idxs=metadata.keys())
        return obj


    def getMetadata(self, dom, mapping):
        headers = self.getHeaders(dom, mapping)
        metadata = {}
        for key, value in headers:
            if key == 'license':
                mdt = getToolByName(self.context, 'portal_moduledb')
                mdt.getLicenseData(value)
            if value: metadata[key] = value
        return metadata
