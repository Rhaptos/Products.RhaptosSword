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

from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
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
         'descriptionOfChanges' : 'descriptionOfChanges',
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


    def createObject(self, context, name, content_type, request):
        # see if the request has a atompub payload that specifies,
        # module id in "source" or "mdml:derived_from" in ATOM entry.
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            # find our marker elements
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)
            body.seek(0)
            elements = dom.getElementsByTagNameNS(
                "http://purl.org/dc/terms/", 'source')
            if len(elements) > 0:
                # now we can fork / derive the module
                obj = self.deriveModule(
                    str(elements[0].firstChild.nodeValue))
                return obj

        return super(RhaptosWorkspaceSwordAdapter, self).createObject(
            context, name, content_type, request)


    def deriveModule(self, url):
        """ We checkout the object, fork it, remove the temp one and 
            return the forked copy.
        """
        module_id = url.split('/')[-1]
        # Fetch module and area
        version = 'latest'
        content_tool = getToolByName(self.context, 'content')
        module = content_tool.getRhaptosObject(module_id, version)
        area = self.context
        # We create a copy that we want to clean up later, let's track the id
        to_delete_id = area.generateUniqueId()
        area.invokeFactory(id=to_delete_id, type_name=module.portal_type)
        obj = area._getOb(to_delete_id)

        # module must be checked out to area before a fork is possible
        obj.setState('published')
        obj.checkout(module.objectId)

        # Do the fork
        forked_obj = obj.forkContent(
            license=module.getDefaultLicense(), return_context=True,
        )
        forked_obj.setState('created')
        forked_obj.setGoogleAnalyticsTrackingCode(None)

        # Delete temporary copy
        if to_delete_id:
            area.manage_delObjects(ids=[to_delete_id])
        return forked_obj


    def updateObject(self, obj, filename, request, response, content_type):

        def updateMetadata(obj, fp):
            dom = parse(fp)
            metadata = self.getMetadata(dom, METADATA_MAPPING)
            # better make sure we have a title while deriving content
            metadata.setdefault('title', obj.title)
            # we remove descriptionOfChanges because the update_metadata
            # script cannot cope with it.
            descriptionOfChanges = metadata.pop(
                'descriptionOfChanges', '')
            if descriptionOfChanges:
                obj.logAction('create', descriptionOfChanges)
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
            updateMetadata(obj, body)
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


class RhaptosContentRetrieveAdapter(RetrieveContent):

    def __call__(self):
        return self.context.module_export(format='zip')
