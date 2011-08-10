from DateTime import DateTime
from xml.dom.minidom import parse

from zope.interface import Interface, implements
from zope.publisher.interfaces.http import IHTTPRequest
from zope.component import adapts, getMultiAdapter, queryAdapter, queryUtility
from webdav.NullResource import NullResource

from Products.CMFCore.utils import getToolByName
from Products.CMFCore.interfaces import IFolderish

from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

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
        if content_type in self.ATOMPUB_CONTENT_TYPES:
            body = request.get('BODYFILE')
            body.seek(0)
            dom = parse(body)

            obj = obj.__of__(self.context)
            metadata = self.getMetadata(dom, METADATA_MAPPING)
            obj.update_metadata(**metadata)
            #self.addRoles(obj, dom)
            obj.reindexObject(idxs=metadata.keys())
        return obj


    def getMetadata(self, dom, mapping):
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
    
    depositreceipt = ViewPageTemplateFile('depositreceipt.pt')

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


class DepositReceipt(BrowserView):
    """ This extends the SWORD v 2.0 Deposit Receipt to:
        - List role requests.
        - Show whether the license has been signed by the author and all
            contributors.
        - What contributors (see above: author, editor, etc), still need
            to accept their roles on the document.
        - Show whether all required metadata has been provided (including
            the ‘description-of-changes’ if this is a new version of
            existing content).

        TODO:
        Decide how to handle differences between "In-Progress: true" and
        "In-Progress: false" HTTP headers.
    """
    implements(ISWORDDepositReceipt)

    def __call__(self):
        """ Temp call method as debug hook.
        """
        return self.index()
    

    def pending_collaborations(self):
        return self.context.getPendingCollaborations()


    def get_user(self, userid):
        pmt = getToolByName(self.context, 'portal_membership')
        return pmt.getMemberById(userid)


    def get_roles(self, collaboration_requests):
        roles_and_users = {}
        for userid, collab_request in collaboration_requests.items():
            roles = collab_request.roles 
            for role, action in roles.items():
                userids = roles_and_users.get(role, '')
                userids = userids + ' %s' %userid
                roles_and_users[role] = userids
        return roles_and_users
