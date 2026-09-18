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
    const finishLabel = form.getAttribute("data-finish-label") || "Continue";
    const discoverIndex = steps.findIndex(function (step) {
        return step.getAttribute("data-role") === "discover";
    });
    const tablesIndex = steps.findIndex(function (step) {
        return step.getAttribute("data-role") === "tables";
    });
    const reviewIndex = steps.findIndex(function (step) {
        return step.getAttribute("data-role") === "review";
    });
    const needsDiscover = discoverIndex >= 0;

    let current = 1;
    let discovered = [];
    let discoveredColumns = {};
    let discoverOk = false;
    let readonlyRole = false;

    function csrfToken() {
        const input = form.querySelector("[name=csrfmiddlewaretoken]");
        return input ? input.value : "";
    }

    function selectedDatabase() {
        const selected = form.querySelector("input[name=engine]:checked");
        return selected ? selected.parentElement.textContent.trim() : "PostgreSQL";
    }

    function showError(message) {
        if (!errorBox) return;
        errorBox.hidden = !message;
        errorBox.textContent = message || "";
        if (success) success.hidden = true;
        discoverOk = false;
    }

    function renderTables() {
        if (!tableList) return;
        tableList.innerHTML = discovered.map(function (table) {
            const cols = discoveredColumns[table.name] || [];
            const columnHtml = cols.map(function (column) {
                const value = table.name + "." + column;
                return (
                    '<label class="page-meta" style="display:block;margin:.25rem 0 0 1.5rem;">' +
                    '<input type="checkbox" name="allowed_columns" value="' + value + '" checked> ' +
                    column +
                    "</label>"
                );
            }).join("");
            return (
                '<div class="table-row">' +
                '<label><input type="checkbox" name="allowed_tables" value="' + table.name + '" checked> ' +
                "<strong>" + table.name + "</strong></label>" +
                '<div class="page-meta">Choose columns QueryMind may read</div>' +
                columnHtml +
                "</div>"
            );
        }).join("");
    }

    function selectedColumns() {
        return Array.from(form.querySelectorAll("input[name=allowed_columns]:checked")).map(function (el) {
            return el.value;
        });
    }

    function renderReview() {
        if (!reviewCard) return;
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
        const columns = selectedColumns();
        const llm = (form.querySelector("input[name=llm_backend]:checked") || {}).value;
        reviewCard.innerHTML =
            (llm ? "<p><strong>Chat model:</strong> " + (llm === "online" ? "Online (Gemini)" : "Local (Ollama)") + "</p>" : "") +
            "<p><strong>Work:</strong> " + industry + "</p>" +
            "<p>" + business + "</p>" +
            "<p><strong>Information you keep:</strong> " + (keeps.join(", ") || "Not specified") + "</p>" +
            "<p><strong>Database:</strong> " + selectedDatabase() + " — " + ((form.db_name && form.db_name.value) || "") + " on " + ((form.db_host && form.db_host.value) || "") + "</p>" +
            "<p><strong>Role:</strong> " + (readonlyRole ? "Read-only" : "Connected (not a confirmed read-only role)") + "</p>" +
            "<p><strong>Allowed tables:</strong> " + (allowed.join(", ") || "None") + "</p>" +
            "<p><strong>Allowed columns:</strong> " + (columns.join(", ") || "None") + "</p>" +
            "<p><strong>Unavailable to QueryMind:</strong> " + (excluded.join(", ") || "None") + "</p>" +
            "<p class=\"page-meta\">If a table or column is unavailable, QueryMind will act as if it does not exist.</p>";
    }

    function showStep() {
        steps.forEach(function (step, index) {
            step.hidden = index + 1 !== current;
        });
        if (progress) progress.style.width = Math.round((current / steps.length) * 100) + "%";
        if (stepLabel) stepLabel.textContent = "Step " + current + " of " + steps.length;
        backBtn.disabled = current === 1;
        nextBtn.textContent = current === steps.length ? finishLabel : "Continue";
        if (tablesIndex >= 0 && current === tablesIndex + 1) renderTables();
        if (reviewIndex >= 0 && current === reviewIndex + 1) renderReview();
    }

    function discover() {
        const body = new URLSearchParams();
        body.set("db_host", form.db_host.value);
        body.set("db_port", form.db_port.value);
        body.set("db_name", form.db_name.value);
        body.set("db_user", form.db_user.value);
        body.set("db_password", form.db_password.value);
        const engine = form.querySelector("input[name=engine]:checked");
        if (engine) body.set("engine", engine.value);
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
                discoveredColumns = {};
                return false;
            }
            discovered = (result.data.tables || []).map(function (name) {
                return { name: name };
            });
            discoveredColumns = result.data.columns || {};
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

    document.querySelectorAll("input[name=engine]").forEach(function (input) {
        input.addEventListener("change", function () {
            document.querySelectorAll(".db-option").forEach(function (el) {
                el.classList.remove("selected");
            });
            input.closest(".db-option").classList.add("selected");
            const port = document.getElementById("db_port");
            if (port && input.getAttribute("data-default-port")) {
                port.value = input.getAttribute("data-default-port");
            }
            discoverOk = false;
            if (success) success.hidden = true;
        });
    });

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
        if (needsDiscover && current === discoverIndex + 1) {
            if (!discoverOk) {
                discover().then(function (ok) {
                    if (!ok) return;
                    current += 1;
                    showStep();
                });
                return;
            }
        }
        if (tablesIndex >= 0 && current === tablesIndex + 1) {
            const allowed = form.querySelectorAll("input[name=allowed_tables]:checked");
            if (!allowed.length) {
                alert("Choose at least one table QueryMind may use. This is a security boundary.");
                return;
            }
            const missing = Array.from(allowed).filter(function (input) {
                const prefix = input.value + ".";
                return !Array.from(form.querySelectorAll("input[name=allowed_columns]:checked")).some(function (col) {
                    return col.value.indexOf(prefix) === 0;
                });
            });
            if (missing.length) {
                alert("Choose at least one column on each allowed table.");
                return;
            }
        }
        if (current < steps.length) {
            current += 1;
            showStep();
            return;
        }
        if (needsDiscover && (!discoverOk || !discovered.length)) {
            alert("Connect to the database and discover live tables before asking.");
            current = discoverIndex + 1;
            showStep();
            return;
        }
        form.submit();
    });

    showStep();
})();
