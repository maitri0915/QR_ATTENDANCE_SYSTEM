
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    initializePasswordToggles();
    initializeFormProtection();
    initializeAutoDismissAlerts();
    initializeCurrentNavigation();
});

/**
 * Show or hide password fields.
 * Works with inputs using data-password-toggle="inputId".
 */
function initializePasswordToggles() {
    const toggleButtons = document.querySelectorAll(
        "[data-password-toggle]"
    );

    toggleButtons.forEach((button) => {
        const inputId = button.getAttribute("data-password-toggle");
        const passwordInput = document.getElementById(inputId);

        if (!passwordInput) return;

        button.addEventListener("click", () => {
            const shouldShow = passwordInput.type === "password";
            passwordInput.type = shouldShow ? "text" : "password";

            const icon = button.querySelector("i");

            if (icon) {
                icon.classList.toggle("bi-eye", !shouldShow);
                icon.classList.toggle("bi-eye-slash", shouldShow);
            }

            button.setAttribute(
                "aria-label",
                shouldShow ? "Hide password" : "Show password"
            );

            button.setAttribute("aria-pressed", String(shouldShow));
        });
    });
}

/**
 * Prevent accidental repeated submissions.
 * Does not interfere with forms that use JavaScript event handlers.
 */
function initializeFormProtection() {
    document.querySelectorAll("form[data-prevent-double-submit]")
        .forEach((form) => {
            form.addEventListener("submit", () => {
                if (!form.checkValidity()) return;

                const submitButton = form.querySelector(
                    'button[type="submit"], input[type="submit"]'
                );

                if (!submitButton || form.dataset.submitting === "true") {
                    return;
                }

                form.dataset.submitting = "true";
                submitButton.disabled = true;
                submitButton.setAttribute("aria-busy", "true");
            });
        });
}

/**
 * Dismiss alerts when their close button is clicked.
 * Bootstrap's own dismiss behavior remains supported.
 */
function initializeAutoDismissAlerts() {
    document.querySelectorAll("[data-auto-dismiss]")
        .forEach((alert) => {
            const delay = Number(alert.dataset.autoDismiss);

            if (!Number.isFinite(delay) || delay <= 0) return;

            window.setTimeout(() => {
                if (!alert.isConnected) return;

                if (window.bootstrap?.Alert) {
                    window.bootstrap.Alert.getOrCreateInstance(alert).close();
                } else {
                    alert.remove();
                }
            }, delay);
        });
}

/**
 * Highlight the navigation link matching the current URL.
 */
function initializeCurrentNavigation() {
    const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";

    document.querySelectorAll(".app-navbar .navbar-nav a.nav-link")
        .forEach((link) => {
            try {
                const linkUrl = new URL(link.href, window.location.origin);
                const linkPath = linkUrl.pathname.replace(/\/+$/, "") || "/";

                if (linkPath === currentPath) {
                    link.classList.add("active");
                    link.setAttribute("aria-current", "page");
                }
            } catch {
                // Ignore invalid links without breaking other navigation.
            }
        });
}