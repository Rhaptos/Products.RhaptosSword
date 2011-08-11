from xml.dom.minidom import parse
from zipfile import BadZipfile

from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, queryAdapter
from AccessControl import getSecurityManager

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent

from rhaptos.swordservice.plone.interfaces import ISWORDDepositReceipt
from rhaptos.swordservice.plone.browser.sword import PloneFolderSwordAdapter
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 


class ValidationError(Exception):
    """ Basic validation error
    """

CNX_MD_NAMESPACE = 'http://cnx.rice.edu/mdml'

METADATA_MAPPING =\
        {'title'   : 'title',
         'keyword' : 'keywords',
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
        body = request.get('BODYFILE')
        body.seek(0)
        obj = obj.__of__(self.context)
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            dom = parse(body)
            metadata = self.getMetadata(dom, METADATA_MAPPING)
            obj.update_metadata(**metadata)
            #self.addRoles(obj, dom)
            obj.reindexObject(idxs=metadata.keys())
        elif content_type == 'application/zip':
            try:
                kwargs = {
                    'original_file_name': 'sword-import-file',
                    'user_name': getSecurityManager().getUser().getUserName()
                }
                text, subobjs, meta = doTransform(obj, "sword_to_folder",
                    body.read(), meta=1, **kwargs)
                if text:
                  obj.manage_delObjects([obj.default_file,])

                  obj.invokeFactory('CNXML Document', obj.default_file, file=text, idprefix='zip-')
                makeContent(obj, subobjs)

                # Parse the returned mdml and set attributes up on the ModuleEditor object
                # Add any additional, unmatched, aka uncredited authors
                props = meta['properties']
                obj.updateProperties(props)
                # Make sure the metadata gets into the cnxml
                obj.editMetadata()
            except OOoImportError, e:
                transaction.abort()
                context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems transforming the openoffice or word document." % (memberId, new_id))
                message = context.translate("message_could_not_import", {"errormsg":e}, domain="rhaptos",
                                            default="Could not import file. %s" % e)
                response.setStatus('BadRequest')
                return state.set(status='SwordImportError', portal_status_message=message)
            except BadZipfile, e:
                transaction.abort()
                context.plone_log("SWORD Import for %s with id=%s: Aborted. There were problems with the uploaded zip file." % (memberId, new_id))
                response.setStatus('BadRequest')
                state.setStatus('SwordErrorZip')
                return state.set(context=context)
                
        return obj


    def getMetadata(self, dom, mapping):
        """
        TODO:
            Set the attribution_note on the module.
            Investigate using 'getLanguagesWithoutSubtypes' and
            'getLanguageWithSubtypes' instead of sql call.

        """
        mdt = getToolByName(self.context, 'portal_moduledb')
        headers = self.getHeaders(dom, mapping)
        metadata = {}
        for key, value in headers:
            if key == 'license':
                mdt = getToolByName(self.context, 'portal_moduledb')
                mdt.getLicenseData(value)
            if key == 'keywords':
                value = value.split('\n')
            if key == 'language':
                plt = getToolByName(self.context, 'portal_languages')
                languages = plt.getAvailableLanguages()
                if value not in languages.keys():
                    raise ValidationError('The language %s is not valid.' %value)
            if key == 'subject':
                values = value.split('\n')
                subjects = mdt.sqlGetTags(scheme='ISKME subject').tuples()
                subjects = [tup[1].lower() for tup in subjects]
                for v in values:
                    if v.lower() not in subjects:
                        raise ValidationError('The subject %s is invalid.' %v)

            if value: metadata[key] = value
        return metadata


    def addRoles(self, obj, dom):
        newRoles = {}
        for element in dom.getElementsByTagNameNS(CNX_MD_NAMESPACE, 'role'):
            role = element.getAttribute('type').capitalize()
            newRoles[role] = element.firstChild.nodeValue.split(' ')

        user_role_delta = obj.generateCollaborationRequests(
                newUser=True, newRoles=newRoles)
        for p in user_role_delta.keys():
            collabs = list(obj.getCollaborators())
            if p not in collabs:
                obj.addCollaborator(p)
                obj.requestCollaboration(p, user_role_delta[p])


    def updateRoles(self, obj, dom):
        """
        Compute the updated roles
        - just the list of userids and roles in the xml
        Compute the deleted roles
        - collaborators that are currently on the object, but not in the xml
        Compute the cancelled roles
        - pending collaboration request for which there are no roles in the xml
        """
        updateRoles = {}
        deleteRoles = []
        cancelRoles = []
        for element in dom.getElementsByTagNameNS(CNX_MD_NAMESPACE, 'role'):
            role = element.getAttribute('type').capitalize()
            updateRoles[role] = element.firstChild.nodeValue.split(' ')
        pending_collaborations = obj.getPendingCollaborations()
        for user_id in pending_collaborations.keys():
            if user_id not in updateRoles.keys() and user_id != obj.Creator():
                cancelRoles.append(user_id)
        for user_id in obj.getCollaborators():
            if user_id not in updateRoles.keys() and user_id != obj.Creator():
                deleteRoles.append(user_id)

        obj.update_roles(updateRoles = updateRoles,
                         deleteRoles = deleteRoles,
                         cancelRoles = cancelRoles)


class DepositReceiptAdapter(object):
    """ Adapts a context and renders an edit document for it. This should
        only be possible for uploaded content.
    """
    implements(ISWORDDepositReceipt)
    
    depositreceipt = ViewPageTemplateFile('browser/depositreceipt.pt')

    def __init__(self, context):
        self.context = context

    def __call__(self, swordview):
        return self.depositreceipt

    def information(self, ob=None):
        """ Return additional or overriding information about our context. By
            default there is no extra information, but if you register an
            adapter for your context that provides us with a
            ISWORDContentAdapter, you can generate or override that extra
            information by implementing a method named information that
            returns a dictionary.  Valid keys are author and updated. """
        if ob is None:
            ob = self.context
        adapter = queryAdapter(ob, ISWORDContentAdapter)
        if adapter is not None:
            return adapter.information()
        return {}

