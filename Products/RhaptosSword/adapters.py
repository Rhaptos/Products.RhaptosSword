from xml.dom.minidom import parse
from zipfile import BadZipfile
from email import message_from_file
from StringIO import StringIO

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
from rhaptos.swordservice.plone.browser.sword import RetrieveContent
from rhaptos.swordservice.plone.browser.sword import ISWORDContentUploadAdapter 
from rhaptos.swordservice.plone.browser.sword import ISWORDRetrieveContentAdapter


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


class IRhaptosContentRetrieveAdapter(ISWORDRetrieveContentAdapter):
    """ Marker interface for SWORD service specific to the Rhaptos 
        implementation.
    """


class RhaptosWorkspaceSwordAdapter(PloneFolderSwordAdapter):
    """ Rhaptos specific implement of the SWORD folder adapter.
    """
    adapts(IFolderish, IHTTPRequest)
    
    def generateFilename(self, name):
        """ Override this method to provide a more sensible name in the
            absence of content-disposition. """
        return super(RhaptosWorkspaceSwordAdapter, self).generateFilename(
            name, type_name='Module')

    def _splitRequest(self, request):
        """ This is only to be used for multipart uploads. The first
            part is the atompub bit, the second part is the payload. """
        request.stdin.seek(0)
        message = message_from_file(request.stdin)
        atom, payload = message.get_payload()

        # Call get_payload with decode=True, so it can handle the transfer
        # encoding for us, if any.
        atom = atom.get_payload(decode=True)
        payload = payload.get_payload(decode=True)

        return atom, payload


    def updateObject(self, obj, filename, request, response, content_type):

        def updateMetadata(obj, fp):
            dom = parse(fp)
            metadata = self.getMetadata(dom, METADATA_MAPPING)
            obj.update_metadata(**metadata)
            # IB: Always add? Or replace when modifying existing content?
            self.addRoles(obj, dom)
            obj.reindexObject(idxs=metadata.keys())

        def updateContent(obj, fp):
            kwargs = {
                'original_file_name': 'sword-import-file',
                'user_name': getSecurityManager().getUser().getUserName()
            }
            text, subobjs, meta = doTransform(obj, "zip_to_folder",
                fp.read(), meta=1, **kwargs)
            # For a new document, it will contain a blank index.cnxml. For
            # existing documents, we want to replace all of it anyway. Either
            # way, we want to  delete the contents of the module and replace
            # it. Unless we have no text, then leave the default empty
            # document alone
            obj.manage_delObjects(
                filter(lambda x: x!=obj.default_file, obj.objectIds()))
            if text:
                obj.manage_delObjects([obj.default_file,])
                obj.invokeFactory('CNXML Document', obj.default_file,
                    file=text, idprefix='zip-')
            makeContent(obj, subobjs)

        obj = obj.__of__(self.context)
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            updateMetadata(body)
        elif content_type == 'application/zip':
            body = request.get('BODYFILE')
            body.seek(0)
            updateContent(obj, body)
        elif content_type.startswith('multipart/'):
            atom, payload = self._splitRequest(request)
            updateMetadata(obj, StringIO(atom))
            updateContent(obj, StringIO(payload))

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
            newRoles[role] =\
                    [str(id) for id in element.firstChild.nodeValue.split(' ')]

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


class RhaptosContentRetrieveAdapter(RetrieveContent):

    def __call__(self):
        return self.context.module_export(format='zip')
