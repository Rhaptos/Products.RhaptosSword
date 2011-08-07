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


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)

    def updateObject(self, obj, filename, request, response, content_type):
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)
            headers = self.getHeaders(dom, self.METADATA_MAPPING)
            metadata = {}
            for key, value in headers:
                if value: metadata[key] = value
            obj = obj.__of__(self.context)
            self.updateMetadata(obj, metadata)
            obj.reindexObject(idxs=metadata.keys())
        return obj

    def updateMetadata(self, obj, metadata):
        title = metadata.get('title', '').strip()
        abstract = metadata.get('abstract', '').strip()
        language = metadata.get('language', '').strip()
        subject = metadata.get('subject', [])
        license = metadata.get('license', '').strip()
        keywords = [kw.strip() for kw in metadata.get('keywords', [])\
                    if kw.strip()]
        GoogleAnalyticsTrackingCode =\
                metadata.get('GoogleAnalyticsTrackingCode', '').strip()

        # Uniqify and remove empty items from list
        keywords = filter(None, dict(map(None,keywords,[])).keys())
        keywords.sort(lambda x,y: cmp(x.lower(),y.lower()))

        obj.manage_changeProperties(language=language)
        obj.manage_changeProperties({'title' : title,
                                     'abstract' : abstract,
                                     'keywords' : keywords,
                                     'revised' : DateTime(),
                                     'subject' : subject
                                    })
        
        if license:
            try:
                mdt = getToolByName(self.context, 'portal_moduledb')
                mdt.getLicenseData(license)
                obj.setLicense(license)
            except IndexError:
                # TODO: Fixme: we should raise some error, etc. here
                license = None
            except AttributeError:
                obj.manage_changeProperties(license=license)

        if GoogleAnalyticsTrackingCode:
            obj.setGoogleAnalyticsTrackingCode(GoogleAnalyticsTrackingCode)

        obj.editMetadata()
