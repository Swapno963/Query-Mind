(function () {
    const openBtn = document.querySelector("[data-copy-key]");
    const modal = document.getElementById("copy-key-modal");
    const form = document.getElementById("copy-key-form");
    if (!openBtn || !modal || !form) return;

    const errorBox = document.getElementById("copy-key-error");
    const successBox = document.getElementById("copy-key-success");
    const passwordInput = document.getElementById("copy-key-password");
    const actionUrl = openBtn.getAttribute("data-action-url") || window.location.pathname;

    function csrfToken() {
        const input = form.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function show(el, message) {
        if (!el) return;
        el.hidden = !message;
        el.textContent = message || "";
    }

    function openModal() {
        modal.hidden = false;
        document.body.classList.add("qm-modal-open");
        show(errorBox, "");
        show(successBox, "");
        if (passwordInput) {
            passwordInput.value = "";
            passwordInput.focus();
        }
    }

    function closeModal() {
        modal.hidden = true;
        document.body.classList.remove("qm-modal-open");
    }

    openBtn.addEventListener("click", openModal);
    modal.querySelectorAll("[data-copy-key-close]").forEach(function (el) {
        el.addEventListener("click", closeModal);
    });
    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !modal.hidden) closeModal();
    });

    form.addEventListener("submit", function (event) {
        event.preventDefault();
        show(errorBox, "");
        show(successBox, "");
        const body = new FormData(form);
        fetch(actionUrl, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                Accept: "application/json",
                "X-CSRFToken": csrfToken(),
            },
            body: body,
            credentials: "same-origin",
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    return { ok: response.ok, data: data };
                });
            })
            .then(function (result) {
                if (!result.ok || !result.data || !result.data.ok) {
                    show(errorBox, (result.data && result.data.error) || "Could not copy the key.");
                    return;
                }
                const key = result.data.key || "";
                const done = function () {
                    show(successBox, result.data.message || "Copied to clipboard.");
                    if (passwordInput) passwordInput.value = "";
                    window.setTimeout(closeModal, 900);
                };
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(key).then(done).catch(function () {
                        show(errorBox, "Could not write to the clipboard. Copy the key from the page after refresh.");
                    });
                    return;
                }
                done();
            })
            .catch(function () {
                show(errorBox, "Could not copy the key. Check your password and try again.");
            });
    });
})();
