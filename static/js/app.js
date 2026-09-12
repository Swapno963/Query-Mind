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
})();
