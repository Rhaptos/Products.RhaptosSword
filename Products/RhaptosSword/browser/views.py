from zope.interface import Interface, implements
from Acquisition import aq_inner
import transaction

from Products.CMFCore.utils import getToolByName

from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from rhaptos.swordservice.plone.interfaces import ISWORDEditIRI
from rhaptos.swordservice.plone.browser.sword import SWORDStatement
from rhaptos.swordservice.plone.browser.sword import EditIRI as BaseEditIRI
from rhaptos.atompub.plone.browser.atompub import IAtomFeed

from Products.RhaptosSword.adapters import METADATA_MAPPING

class EditIRI(BaseEditIRI):
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
    __name__ = "edit"
    implements(ISWORDEditIRI)

    depositreceipt = ViewPageTemplateFile('depositreceipt.pt')
    
    def __init__(self, context, request):
        super(EditIRI, self).__init__(context, request)
        self.pmt = getToolByName(self.context, 'portal_membership')


    def _handlePublish(self):
        # We have to commit the transaction, otherwise the object has a blank
        # _p_jar and cannot be moved. And if it cannot be moved it cannot be
        # published.
        transaction.commit()
        context = aq_inner(self.context)
        description_of_changes = context.message
        context.publishContent(message=description_of_changes)


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


    def has_required_metadata(self):
        obj = self.context.aq_inner
        for key, value in METADATA_MAPPING.items():
            if not getattr(obj, key, None): return False
        return True

    
    def subject(self):
        return ', '.join(self.context.subject) 


    def derived_modules(self):
        return self.context.objectValues(spec='Module')
    
    def fullname(self, user_id):
        user = self.pmt.getMemberById(user_id)
        return user.getProperty('fullname')


    def treatment(self):
        return get_treatment(self.context)


    def email(self, user_id):
        user = self.pmt.getMemberById(user_id)
        return user.getProperty('email')


class AtomFeed(BrowserView):
    """
    """
    def getAuthors(self):
        authors = getattr(self.context, 'authors', '')
        return ' '.join(authors)

    
    def getLicense(self):
        license = getattr(self.context, 'license', None)
        return license


    def entries(self):
        meta_types = ['CMF CNXML File', 'UnifiedFile',]
        return self.context.objectValues(spec=meta_types)


class RhaptosSWORDStatement(SWORDStatement):
   
    def __init__(self, context, request):
        super(RhaptosSWORDStatement, self).__init__(context, request)
        self.pmt = getToolByName(self.context, 'portal_membership')
        self.missing_metadata = self.check_metadata()
        self.has_required_metadata = True
        if self.missing_metadata: self.has_required_metadata = False


    def check_metadata(self):
        obj = self.context.aq_inner
        missing_metadata = []
        for key, value in METADATA_MAPPING.items():
            if not getattr(obj, key, None):
                missing_metadata.append(key)
        return missing_metadata


    def collaborators(self):
        pending_collabs = self.pending_collabs()
        collaborators = {'pending_collabs': pending_collabs, }
        return collaborators
    

    def pending_collabs(self):
        return self.context.getPendingCollaborations()

    
    def current_collabs(self):
        return {} 

    
    def deposited_by(self):
        return ', '.join(self.context.authors)

    
    def treatment(self):
        return get_treatment(self.context)


def get_treatment(context):
    module_name = context.title
    description_of_changes = context.message
    message = """Module '%s' was imported via the SWORD API.
    * You can preview your module here to see what it will look like once it is published.
    * The current description of the changes you have made for this version of the module: "%s"
    """ %(module_name, description_of_changes)
    publication_requirements = get_publication_requirements(context)
    if publication_requirements:
        message += 'Publication Requirements:'
        message += publication_requirements
    return message


def get_publication_requirements(context):
    requirements = ""
    if not context.license:
        for user_id in context.authors:
            user = context.pmt.getMemberById(user_id)
            fullname = user.getProperty('fullname')
            requirements += '%s (account:%s), will need to sign the license.\n'\
                             %(fullname, user_id)

    pending_collaborations = context.getPendingCollaborations()
    if pending_collaborations:
        requirements += 'The following contributors must agree to be listing on the module and sign the license agreement here.'
    for user_id, collab in pending_collaborations:
        user = context.pmt.getMemberById(user_id)
        fullname = user.getProperty('fullname')
        requirements += '%s (account:%s)' %(fullname, user_id)
    if not context.message:
        requirements += 'You must describe the changes that you have made to this version before publishing.'
    return requirements
