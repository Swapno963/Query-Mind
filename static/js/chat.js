(function () {
    const messagesEl = document.getElementById("chat-messages");
    const form = document.getElementById("chat-form");
    const textarea = document.getElementById("message-input");

    function scrollToBottom() {
        if (!messagesEl) return;
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function highlightCode() {
        if (window.hljs) {
            window.hljs.highlightAll();
        }
    }

    function resizeComposer() {
        if (!textarea) return;
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }

    function startStream(root) {
        const url = root.dataset.streamUrl;
        if (!url || root.dataset.streaming === "1") return;
        root.dataset.streaming = "1";

        const messageId = root.dataset.messageId;
        const contentDiv = document.getElementById("ai-content-" + messageId);
        const timestampDiv = document.getElementById("ai-timestamp-" + messageId);
        const statusDiv = document.getElementById("query-status-" + messageId);
        const sqlPanel = document.getElementById("sql-panel-" + messageId);
        const sqlCode = document.getElementById("sql-code-" + messageId);
        const conversationId = root.dataset.conversationId;
        const modelName = root.dataset.modelName || "";

        let aiContent = "";
        contentDiv.classList.add("streaming");
        if (statusDiv) {
            statusDiv.classList.add("visible");
            statusDiv.textContent = "Thinking…";
        }

        const eventSource = new EventSource(url);

        function hideStatus() {
            if (statusDiv) statusDiv.classList.remove("visible");
        }

        eventSource.onmessage = function (event) {
            const data = JSON.parse(event.data);

            if (data.type === "status") {
                if (statusDiv) {
                    statusDiv.classList.add("visible");
                    statusDiv.textContent = data.content;
                }
            } else if (data.type === "sql") {
                if (sqlPanel && sqlCode) {
                    sqlPanel.hidden = false;
                    sqlCode.textContent = data.content;
                }
            } else if (data.type === "token" || data.type === "result") {
                aiContent += data.content;
                contentDiv.textContent = aiContent;
                hideStatus();
                scrollToBottom();
            } else if (data.type === "done") {
                eventSource.close();
                contentDiv.classList.remove("streaming");
                if (timestampDiv) {
                    timestampDiv.textContent = data.timestamp + (modelName ? " • " + modelName : "");
                }
                const csrf = document.querySelector("[name=csrfmiddlewaretoken]");
                if (csrf && aiContent) {
                    fetch("/chat/" + conversationId + "/render-markdown/", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRFToken": csrf.value,
                        },
                        body: JSON.stringify({ content: aiContent }),
                    })
                        .then(function (response) { return response.text(); })
                        .then(function (html) {
                            contentDiv.innerHTML = html;
                            highlightCode();
                            scrollToBottom();
                        });
                }
            } else if (data.type === "error") {
                eventSource.close();
                contentDiv.classList.remove("streaming");
                hideStatus();
                contentDiv.innerHTML = "<em>Error: " + data.content + "</em>";
            }
        };

        eventSource.onerror = function () {
            eventSource.close();
            contentDiv.classList.remove("streaming");
            if (!aiContent) {
                contentDiv.innerHTML = "<em>Error: Connection lost.</em>";
            }
            hideStatus();
        };
    }

    function bootPendingStreams() {
        document.querySelectorAll("[data-stream-url]").forEach(startStream);
    }

    if (textarea) {
        textarea.addEventListener("input", resizeComposer);
        textarea.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (textarea.value.trim() && form) {
                    form.requestSubmit();
                }
            }
        });
    }

    document.body.addEventListener("htmx:afterSwap", function () {
        bootPendingStreams();
        highlightCode();
        scrollToBottom();
        if (textarea) {
            textarea.value = "";
            resizeComposer();
        }
    });

    highlightCode();
    scrollToBottom();
    bootPendingStreams();
})();
