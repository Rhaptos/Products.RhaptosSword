from zope.interface import Interface, implements

from Products.CMFCore.utils import getToolByName

from Products.Five import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from rhaptos.swordservice.plone.interfaces import ISWORDDepositReceipt

from Products.RhaptosSword.adapters import METADATA_MAPPING

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

    depositreceipt = ViewPageTemplateFile('depositreceipt.pt')
    
    def __call__(self, upload=True):
        return self.depositreceipt()

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
