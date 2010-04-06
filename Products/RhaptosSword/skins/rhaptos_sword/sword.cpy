## atom.cpy : process sword requests
##parameters=
from Products.CNXMLTransforms.helpers import OOoImportError, doTransform, makeContent
import transaction
from AccessControl import getSecurityManager

request = context.REQUEST
response = context.REQUEST.RESPONSE 
sword_tool = context.sword_tool

acceptingSwordRequests = sword_tool.acceptingSwordRequests

member = context.portal_membership.getAuthenticatedMember()
memberId = str(member)
isAnonymousUser = context.portal_membership.isAnonymousUser()

method = request['REQUEST_METHOD']

context.plone_log("method is %s." % method)
context.plone_log("member is %s." % memberId)
context.plone_log("Accepting Sword Request? %s." % str(acceptingSwordRequests))

if isAnonymousUser:
    response.setStatus('Unauthorized')
    return response
elif method == "GET":
    # service request
    if acceptingSwordRequests:
        state.setStatus('ServiceDiscovery')
        return state.set(context=context)
    else:
        response.setStatus('NotFound')
        return response
elif method == "POST":
    # content post
    if not acceptingSwordRequests:
        response.setStatus('NotFound')
        return response
    else:
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        type_name = 'Module'
        id=context.generateUniqueId(type_name)
        new_id = context.invokeFactory(id=id, type_name=type_name)
        if new_id is None or new_id == '':
           new_id = id
        rme=getattr(context, new_id, None)
        tname = rme.getTypeInfo().Title()
        # Perform the import
        try:
            text = context.REQUEST['BODY']
            kwargs = {'original_file_name':'sword-import-file', 'user_name':getSecurityManager().getUser().getUserName()}
            text, subobjs, meta = doTransform(rme, "sword_to_folder", text, meta=1, **kwargs)
            if text:
                rme.manage_delObjects([rme.default_file,])
                rme.invokeFactory('CNXML Document', rme.default_file, file=text, idprefix='zip-')
            makeContent(rme, subobjs)
            # Parse the returned mdml and set attributes up on the ModuleEditor object
            rme.updateMdmlStr(meta.get('mdml'))

        except OOoImportError, e:
            transaction.abort()
            message = context.translate("message_could_not_import", {"errormsg":e}, domain="rhaptos",
                                        default="Could not import file. %s" % e)
            return state.set(status='failure', portal_status_message=message)
