import string
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class CustomComplexityValidator:
    def validate(self, password, user=None):
        errors = []
        if len(password) < 8:
            errors.append(_("Password must be at least 8 characters long."))
        if not any(c.isupper() for c in password):
            errors.append(_("Password must contain at least one uppercase letter."))
        if not any(c.islower() for c in password):
            errors.append(_("Password must contain at least one lowercase letter."))
        if not any(c.isdigit() for c in password):
            errors.append(_("Password must contain at least one digit."))
        if not any(c in string.punctuation for c in password):
            errors.append(_("Password must contain at least one special character."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _("Your password must include uppercase, lowercase, digit, special character, and be longer than 4 characters.")
