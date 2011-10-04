from rhaptos.swordservice.plone.exceptions import SwordException

class CheckoutUnauthorized(SwordException):
    """ Authenticated user is not authorized to check out the specified module.
    """
    _status = 401
    _title = "Checkout unauthorized"
    _href = "http://purl.org/oerpub/error/CheckoutUnauthorized"

class OverwriteNotPermitted(SwordException):
    """ Overwriting the specified resource is not permitted. """
    _status = 403
    _title = "Overwrite Not Permitted"
    _href = "http://purl.org/oerpub/error/OverwriteNotPermitted"

class PublishUnauthorized(SwordException):
    """ You do not have permission to publish this module right now. """
    _status = 401
    _title = "Publish Unauthorized"
    _href = "http://purl.org/oerpub/error/PublishUnauthorized"

class Unpublishable(SwordException):
    """ The module has errors that must be fixed before it can be published. """
    _status = 412
    _title = "Module Unpublishable"
    _href = "http://purl.org/oerpub/error/Unpublishable"

class TransformFailed(SwordException):
    """ The deposit appears valid, but failed to convert properly. """
    _status = 415
    _title = "Transform Failed"
    _href = "http://purl.org/oerpub/error/TransformFailed"

class DepositFailed(SwordException):
    """ The deposit appears valid, but some contained content is invalid or
        failed to process. """
    _status = 415
    _title = "Deposit Failed"
    _href = "http://purl.org/oerpub/error/DepositFailed"
