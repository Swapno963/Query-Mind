(function () {
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");

    function openSidebar() {
        if (!sidebar) return;
        sidebar.classList.add("open");
        if (backdrop) backdrop.classList.add("visible");
    }

    function closeSidebar() {
        if (!sidebar) return;
        sidebar.classList.remove("open");
        if (backdrop) backdrop.classList.remove("visible");
    }

    document.querySelectorAll("[data-sidebar-open]").forEach(function (btn) {
        btn.addEventListener("click", openSidebar);
    });

    document.querySelectorAll("[data-sidebar-close]").forEach(function (btn) {
        btn.addEventListener("click", closeSidebar);
    });

    if (backdrop) {
        backdrop.addEventListener("click", closeSidebar);
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") closeSidebar();
    });

    document.querySelectorAll("[data-fill-question]").forEach(function (chip) {
        chip.addEventListener("click", function () {
            const textarea = document.getElementById("message-input");
            if (!textarea || textarea.disabled) return;
            textarea.value = chip.getAttribute("data-fill-question") || "";
            textarea.focus();
        });
    });

    const askTextarea = document.getElementById("message-input");
    const askForm = askTextarea && askTextarea.closest("form");
    if (askTextarea && askForm && !document.getElementById("chat-form")) {
        askTextarea.addEventListener("input", function () {
            askTextarea.style.height = "auto";
            askTextarea.style.height = Math.min(askTextarea.scrollHeight, 160) + "px";
        });
        askTextarea.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (askTextarea.value.trim()) askForm.requestSubmit();
            }
        });
    }

    function escapeHtml(value) {
        return value
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function wrap(cls, text) {
        return '<span class="' + cls + '">' + escapeHtml(text) + "</span>";
    }

    function highlightJson(source) {
        const pattern =
            /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[{}\[\]:,]/g;
        let last = 0;
        let html = "";
        source.replace(pattern, function (match, stringLit, isKey, keyword, offset) {
            html += escapeHtml(source.slice(last, offset));
            last = offset + match.length;
            if (stringLit) {
                html += wrap(isKey ? "tok-key" : "tok-str", stringLit);
                if (isKey) html += wrap("tok-punct", isKey);
                return match;
            }
            if (keyword) {
                html += wrap("tok-kw", keyword);
                return match;
            }
            if (/^-?\d/.test(match)) {
                html += wrap("tok-num", match);
                return match;
            }
            html += wrap("tok-punct", match);
            return match;
        });
        html += escapeHtml(source.slice(last));
        return html;
    }

    function highlightBash(source) {
        const pattern =
            /(#[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\$[A-Z_][A-Z0-9_]*)|\b(curl)\b|(--[a-zA-Z0-9-]+|-[A-Za-z])|(\\[ \t]*\n)/g;
        let last = 0;
        let html = "";
        source.replace(pattern, function (match, comment, str, variable, cmd, flag, cont, offset) {
            html += escapeHtml(source.slice(last, offset));
            last = offset + match.length;
            if (comment) html += wrap("tok-comment", comment);
            else if (str) html += wrap("tok-str", str);
            else if (variable) html += wrap("tok-var", variable);
            else if (cmd) html += wrap("tok-cmd", cmd);
            else if (flag) html += wrap("tok-flag", flag);
            else html += wrap("tok-punct", match);
            return match;
        });
        html += escapeHtml(source.slice(last));
        return html;
    }

    document.querySelectorAll("pre.docs-pre[data-lang] code").forEach(function (block) {
        const lang = block.parentElement.getAttribute("data-lang");
        const source = block.textContent;
        if (lang === "json") block.innerHTML = highlightJson(source);
        else if (lang === "bash") block.innerHTML = highlightBash(source);
    });

    const tocLinks = Array.prototype.slice.call(document.querySelectorAll(".docs-toc a"));
    if (tocLinks.length && "IntersectionObserver" in window) {
        const byId = {};
        tocLinks.forEach(function (link) {
            const id = (link.getAttribute("href") || "").replace("#", "");
            if (id) byId[id] = link;
        });
        const observer = new IntersectionObserver(
            function (entries) {
                entries.forEach(function (entry) {
                    if (!entry.isIntersecting) return;
                    tocLinks.forEach(function (link) {
                        link.classList.remove("is-active");
                    });
                    const link = byId[entry.target.id];
                    if (link) link.classList.add("is-active");
                });
            },
            { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
        );
        Object.keys(byId).forEach(function (id) {
            const section = document.getElementById(id);
            if (section) observer.observe(section);
        });
    }
})();
