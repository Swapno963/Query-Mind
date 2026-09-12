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
    const paste = document.getElementById("schema_paste");
    const success = document.getElementById("discover-success");
    const instruction = document.getElementById("discover-instruction");
    const copyBtn = document.getElementById("copy-instruction");

    const instructions = {
        PostgreSQL: "Run this in your database tool, then paste the output:\nSELECT table_name FROM information_schema.tables WHERE table_schema = 'public';",
        MySQL: "Run this in your database tool, then paste the output:\nSHOW TABLES;",
        "Microsoft SQL Server": "Run this in your database tool, then paste the output:\nSELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';",
        "Oracle Database": "Run this in your database tool, then paste the output:\nSELECT table_name FROM user_tables;",
        MongoDB: "Run this in your database tool, then paste the output:\ndb.getCollectionNames()",
    };

    const fallbackTables = [
        { name: "customers", description: "People you sell to or serve" },
        { name: "orders", description: "Purchases or requests" },
        { name: "products", description: "Items or services you offer" },
        { name: "payments", description: "Money received or owed" },
        { name: "staff", description: "People who work with you" },
    ];

    let current = 1;
    let discovered = fallbackTables.slice();

    function selectedDatabase() {
        const input = form.querySelector("input[name=database]:checked");
        return input ? input.value : "PostgreSQL";
    }

    function parsePaste(text) {
        const lines = text.split(/\r?\n/).map(function (line) {
            return line.trim();
        }).filter(Boolean);
        const names = [];
        lines.forEach(function (line) {
            const match = line.match(/[A-Za-z_][A-Za-z0-9_]*/);
            if (match && !/table_name|information_schema|show|select/i.test(match[0])) {
                names.push(match[0]);
            }
        });
        const unique = Array.from(new Set(names)).slice(0, 12);
        if (!unique.length) return fallbackTables.slice();
        return unique.map(function (name) {
            return { name: name, description: "Discovered from your paste" };
        });
    }

    function renderTables() {
        tableList.innerHTML = discovered.map(function (table) {
            return (
                '<label class="table-row">' +
                '<input type="checkbox" name="allowed_tables" value="' + table.name + '" checked>' +
                "<div><strong>" + table.name + "</strong>" +
                '<div class="page-meta">' + table.description + "</div></div></label>"
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
            "<p><strong>Database:</strong> " + selectedDatabase() + "</p>" +
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
        if (current === 3 || current === 4) {
            instruction.textContent = instructions[selectedDatabase()];
            form.querySelectorAll(".db-option").forEach(function (el) {
                el.classList.toggle("selected", el.querySelector("input").checked);
            });
        }
        if (current === 5) {
            discovered = parsePaste(paste.value || "");
            renderTables();
            if (success) {
                success.hidden = !(paste.value || "").trim();
                if (!success.hidden) {
                    success.textContent = "We found " + discovered.length + " tables.";
                }
            }
        }
        if (current === 6) renderReview();
    }

    form.querySelectorAll("input[name=database]").forEach(function (input) {
        input.addEventListener("change", function () {
            form.querySelectorAll(".db-option").forEach(function (el) {
                el.classList.toggle("selected", el.querySelector("input").checked);
            });
            instruction.textContent = instructions[selectedDatabase()];
        });
    });

    if (copyBtn) {
        copyBtn.addEventListener("click", function () {
            navigator.clipboard.writeText(instruction.textContent).then(function () {
                copyBtn.textContent = "Copied";
                setTimeout(function () { copyBtn.textContent = "Copy"; }, 1200);
            });
        });
    }

    if (paste) {
        paste.addEventListener("input", function () {
            if (!success) return;
            const tables = parsePaste(paste.value);
            success.hidden = !(paste.value || "").trim();
            if (!success.hidden) {
                success.textContent = "We found " + tables.length + " tables.";
            }
        });
    }

    backBtn.addEventListener("click", function () {
        if (current > 1) {
            current -= 1;
            showStep();
        }
    });

    nextBtn.addEventListener("click", function () {
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
        form.submit();
    });

    showStep();
})();
