## atom.cpy : process sword requests
##parameters=

request = context.REQUEST
response = context.REQUEST.RESPONSE 
sword_tool = context.sword_tool

acceptingSwordRequests = sword_tool.acceptingSwordRequests

member = context.portal_membership.getAuthenticatedMember()
memberId = str(member)
isAnonymousUser = ( memberId == 'Anonymous User' )

method = request['REQUEST_METHOD']

context.plone_log("method is %s." % method)
context.plone_log("member is %s." % memberId)
context.plone_log("Accepting Sword Request? %s." % str(acceptingSwordRequests))

if method == "GET":
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
    elif isAnonymousUser:
        response.setStatus('NotFound')
        return response
    else:
        # zipped word doc is part of the request
        # state.setStatus('ContentCreation')
        pass




