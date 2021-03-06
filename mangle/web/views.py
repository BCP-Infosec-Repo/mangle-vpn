import logging

from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from mangle.common import config, models
from mangle.web import forms
from mangle.web.decorators import *
from mangle.web.authentication.backend import redirect_login

logger = logging.getLogger(__name__)


@install_required
@credentials_required
@mfa_required
@ensure_csrf_cookie
def show_app(request, *args, **kwargs):
    """
    Renders the web application.
    :return: Response
    """
    if request.user.password_change:
        return redirect("/password")

    return render(request, "index.html")


#######################################
# Installation
#######################################

def show_install(request):
    """
    Renders the application installation page.
    :return: Response
    """
    # do not let the installation run twice
    if config.get_bool("app_installed", True):
        return redirect("/")

    return render(request, "Install.html", {
        "form": request.session.pop("form", {}),
    })


def process_install(request):
    """
    Processes the application installation form.
    :return: Response
    """
    # do not let the installation run twice
    if config.get_bool("app_installed", True):
        return redirect("/")

    form = forms.InstallForm(request.POST)

    if not form.is_valid():
        save_form(request, form)
        return redirect("/install")

    # save() updates the application settings and creates the administrator
    # user that was defined in the form and log the user in
    admin = form.save()
    login(request, admin, "django.contrib.auth.backends.ModelBackend")

    # set the ``app_installed`` setting to True to indicate installation has
    # been performed and the application is ready for use before redirecting
    # the user to the main application
    config.set("app_installed", True)
    return redirect("/")


#######################################
# Authentication
#######################################

@install_required
def show_google_login(request):
    """
    Redirects the user to the Google OAuth2 page.
    :return: Response
    """
    return redirect_login(request)


@install_required
def show_login(request):
    """
    Renders the application login page.
    :return: Response
    """
    return render(request, "Login.html")


@install_required
def process_login(request):
    """
    Processes a user login attempt via username and password.
    :return: Response
    """
    username = request.POST["username"]
    password = request.POST["password"]

    user = authenticate(request, username=username, password=password)

    if not user:
        logout(request)
        request.session["error"] = "Invalid username or password."
        return redirect("/login")

    login(request, user, "django.contrib.auth.backends.ModelBackend")
    return redirect("/")


@install_required
def process_oauth(request):
    """
    Processes an OAuth2 authentication callback request.
    :return: Response
    """
    user = authenticate(request)

    if not user:
        logout(request)
        request.session["error"] = "Invalid username or password."
        return redirect("/login")

    login(request, user, "mangle.web.authentication.oauth2.backend.OAuth2Backend")
    return redirect("/")


@install_required
def process_logout(request):
    """
    Logs the user out of the application.
    :return: Response
    """
    logout(request)
    return redirect("/login")


@install_required
@mfa_required
def show_password_reset(request):
    """
    Renders the password reset page.
    :return: Response
    """
    return render(request, "Password.html")


@install_required
@mfa_required
def process_password_reset(request):
    """
    Renders the password reset page.
    :return: Response
    """
    form = forms.PasswordForm(request.POST)

    if not form.is_valid():
        save_form(request, form)
        return redirect("/password")

    request.user.set_password(form.cleaned_data["password"])
    request.user.password_change = False
    request.user.save()

    login(request, request.user, "django.contrib.auth.backends.ModelBackend")
    request.session["mfa_confirmed"] = True

    return redirect("/")


#######################################
# Two-Factor Authentication
#######################################

@install_required
@credentials_required
def show_mfa(request):
    """
    Displays the two-factor authentication confirmation page.
    :return: Response
    """
    return render(request, "MfaConfirm.html", {
        "errors": request.session.pop("errors", {})
    })


@install_required
@credentials_required
def show_mfa_setup(request):
    """
    Displays the two-factor authentication setup page.
    :return: Response
    """
    if request.user.mfa_enabled:
        return redirect("/")

    return render(request, "MfaSetup.html", {
        "errors": request.session.pop("errors", {})
    })


@install_required
@credentials_required
def process_mfa(request):
    """
    Verifies the submitted two-factor authentication code for the current user.
    :return: Response
    """
    code = request.POST.get("code")

    if not request.user.verify_mfa_code(code):
        request.session["errors"] = {"code": "Invalid authentication code."}

        models.Event.objects.create(
            name="web.error",
            user=request.user,
            detail="Incorrect two-factor authentication code"
        )

        # redirect back to login on invalid two-factor authentication code
        logout(request)
        request.session["error"] = "Invalid two-factor authentication code."
        return redirect("/login")

    # if the user has confirmed their two-factor authentication code then make
    # sure two-factor authentication is enabled for their account
    if not request.user.mfa_enabled:
        request.user.mfa_enabled = True
        request.user.save()

    models.Event.objects.create(
        name="web.login",
        user=request.user,
        detail="Logged in to web application from {}.".format(get_client_ip(request))
    )

    request.session["mfa_confirmed"] = True
    return redirect("/")


#######################################
# Context Processors
#######################################

def base_context_processor(request):
    """
    The base UI context processor.
    :return: dict
    """
    return {
        "error": request.session.pop("error", None),
        "form": request.session.pop("form", {}),
        "oauth2_provider": config.get("oauth2_provider", None),
        "organization": config.get("app_organization", "Mangle"),
    }


#######################################
# Helpers
#######################################

def save_form(request, form):
    """
    Saves the given form data and errors in the request session.
    :return: None
    """
    request.session["form"] = {
        "data": form.data,
        "errors": form.errors,
    }


def get_client_ip(request):
    """
    Returns the remote IP address of the request. This will check the HTTP
    header 'X-FORWARDED-FOR' which SHOULD exist since we are using Nginx to
    proxy the request, but falls back to REMOTE_ADDR if the header is missing.
    :return: str
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]

    return request.META.get("REMOTE_ADDR")
