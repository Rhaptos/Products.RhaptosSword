from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, getMultiAdapter, queryAdapter, queryUtility
from Acquisition import aq_inner, aq_base
from webdav.NullResource import NullResource

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 


class IRhaptosWorkspaceSwordAdapter(ISWORDContentUploadAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)


    def getObject(self, context, filename, request):
        nullresource = NullResource(self.context, filename, request)
        nullresource = nullresource.__of__(self.context)
        nullresource.PUT(self.request, self.response)
        # Look it up and finish up, then return it.
        obj = self.context._getOb(filename)
        return obj


    def updateObject(self, obj, filename, content_type):
        if content_type == ATOMPUB_CONTENT_TYPE:
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)
            mappings = self.getMetadataMapping(METADATA_MAPPING, dom)
            headers = self.getHeaders(dom, mappings)
            obj.update_metadata(headers)
        return obj
