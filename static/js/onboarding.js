(function () {
    const form = document.getElementById("onboarding-form");
    if (!form) return;

    const steps = Array.from(form.querySelectorAll(".wizard-step"));
    const backBtn = document.getElementById("wizard-back");
    const nextBtn = document.getElementById("wizard-next");
    const progress = document.getElementById("wizard-progress");
    const stepLabel = document.getElementById("wizard-step-label");
    const tableList = document.getElementById("table-list");
    const reviewCard = document.getElementById("review-card");
    const success = document.getElementById("discover-success");
    const errorBox = document.getElementById("discover-error");
    const testBtn = document.getElementById("test-connection");

    let current = 1;
    let discovered = [];
    let discoverOk = false;
    let readonlyRole = false;

    function csrfToken() {
        const input = form.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function selectedDatabase() {
        return "PostgreSQL";
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.hidden = !message;
        errorBox.textContent = message || "";
        if (success) success.hidden = true;
        discoverOk = false;
    }

    function renderTables() {
        tableList.innerHTML = discovered.map(function (table) {
            return (
                '<label class="table-row">' +
                '<input type="checkbox" name="allowed_tables" value="' + table.name + '" checked>' +
                "<div><strong>" + table.name + "</strong>" +
                '<div class="page-meta">Discovered from your live PostgreSQL database</div></div></label>'
            );
        }).join("");
    }

    function renderReview() {
        const industry = (form.querySelector("input[name=industry]:checked") || {}).value || "Not specified";
        const business = (form.business && form.business.value.trim()) || "Not described yet";
        const keeps = Array.from(form.querySelectorAll("input[name=keeps]:checked")).map(function (el) {
            return el.value;
        });
        const allowed = Array.from(form.querySelectorAll("input[name=allowed_tables]:checked")).map(function (el) {
            return el.value;
        });
        const excluded = discovered.map(function (t) { return t.name; }).filter(function (name) {
            return allowed.indexOf(name) === -1;
        });
        reviewCard.innerHTML =
            "<p><strong>Work:</strong> " + industry + "</p>" +
            "<p>" + business + "</p>" +
            "<p><strong>Information you keep:</strong> " + (keeps.join(", ") || "Not specified") + "</p>" +
            "<p><strong>Database:</strong> " + selectedDatabase() + " — " + (form.db_name.value || "") + " on " + (form.db_host.value || "") + "</p>" +
            "<p><strong>Role:</strong> " + (readonlyRole ? "Read-only" : "Connected (not a confirmed read-only role)") + "</p>" +
            "<p><strong>Allowed tables:</strong> " + (allowed.join(", ") || "None") + "</p>" +
            "<p><strong>Unavailable to QueryMind:</strong> " + (excluded.join(", ") || "None") + "</p>" +
            "<p class=\"page-meta\">If a table is unavailable, QueryMind will act as if it does not exist.</p>";
    }

    function showStep() {
        steps.forEach(function (step) {
            const n = Number(step.getAttribute("data-step"));
            step.hidden = n !== current;
        });
        progress.style.width = Math.round((current / steps.length) * 100) + "%";
        stepLabel.textContent = "Step " + current + " of " + steps.length;
        backBtn.disabled = current === 1;
        nextBtn.textContent = current === steps.length ? "Ask your data" : "Continue";
        if (current === 5) {
            renderTables();
        }
        if (current === 6) renderReview();
    }

    function discover() {
        const body = new URLSearchParams();
        body.set("db_host", form.db_host.value);
        body.set("db_port", form.db_port.value);
        body.set("db_name", form.db_name.value);
        body.set("db_user", form.db_user.value);
        body.set("db_password", form.db_password.value);
        body.set("csrfmiddlewaretoken", csrfToken());
        if (testBtn) {
            testBtn.disabled = true;
            testBtn.textContent = "Connecting…";
        }
        return fetch("/onboarding/discover/", {
            method: "POST",
            headers: {
                "X-CSRFToken": csrfToken(),
                "X-Requested-With": "XMLHttpRequest",
            },
            body: body,
        }).then(function (response) {
            return response.json().then(function (data) {
                return { ok: response.ok, data: data };
            });
        }).then(function (result) {
            if (!result.data || !result.data.ok) {
                showError((result.data && result.data.error) || "Could not connect to the database.");
                discovered = [];
                return false;
            }
            discovered = (result.data.tables || []).map(function (name) {
                return { name: name };
            });
            readonlyRole = !!result.data.is_readonly_role;
            discoverOk = discovered.length > 0;
            if (errorBox) errorBox.hidden = true;
            if (success) {
                success.hidden = false;
                success.textContent = "Connected. We found " + discovered.length + " tables.";
            }
            return discoverOk;
        }).catch(function () {
            showError("Could not reach QueryMind to test the connection. Try again.");
            return false;
        }).finally(function () {
            if (testBtn) {
                testBtn.disabled = false;
                testBtn.textContent = "Test connection and discover tables";
            }
        });
    }

    if (testBtn) {
        testBtn.addEventListener("click", function () {
            discover();
        });
    }

    ["db_host", "db_port", "db_name", "db_user", "db_password"].forEach(function (name) {
        const input = form.querySelector("[name=" + name + "]");
        if (input) {
            input.addEventListener("input", function () {
                discoverOk = false;
                if (success) success.hidden = true;
            });
        }
    });

    backBtn.addEventListener("click", function () {
        if (current > 1) {
            current -= 1;
            showStep();
        }
    });

    nextBtn.addEventListener("click", function () {
        if (current === 4) {
            if (!discoverOk) {
                discover().then(function (ok) {
                    if (!ok) return;
                    current += 1;
                    showStep();
                });
                return;
            }
        }
        if (current === 5) {
            const allowed = form.querySelectorAll("input[name=allowed_tables]:checked");
            if (!allowed.length) {
                alert("Choose at least one table QueryMind may use. This is a security boundary.");
                return;
            }
        }
        if (current < steps.length) {
            current += 1;
            showStep();
            return;
        }
        if (!discoverOk || !discovered.length) {
            alert("Connect to PostgreSQL and discover live tables before asking.");
            current = 4;
            showStep();
            return;
        }
        form.submit();
    });

    showStep();
})();
