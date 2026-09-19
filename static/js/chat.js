(function () {
    const messagesEl = document.getElementById("chat-messages");
    const form = document.getElementById("chat-form");
    const textarea = document.getElementById("message-input");
    const hint = document.getElementById("composer-hint");

    function scrollToBottom() {
        if (!messagesEl) return;
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    function highlightCode() {
        if (window.hljs) window.hljs.highlightAll();
    }

    function resizeComposer() {
        if (!textarea) return;
        textarea.style.height = "auto";
        textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }

    function setWorking(working) {
        if (textarea) textarea.disabled = working;
        const send = form && form.querySelector(".send-btn");
        if (send) send.disabled = working;
        if (hint && working) hint.textContent = "QueryMind is working…";
        if (hint && !working) {
            hint.textContent = "Answers come from your allowed tables only. Enter to send · Shift + Enter for a new line";
        }
    }

    function errorCardHtml(title, detail) {
        return "<h3>" + title + "</h3><p>" + detail + "</p>";
    }

    function renderRows(container, rows) {
        if (!container || !rows || !rows.length) return;
        const columns = Object.keys(rows[0]);
        let html = '<div class="results-caption">Showing ' + rows.length + " row" + (rows.length === 1 ? "" : "s") + "</div>";
        html += "<table><thead><tr>" + columns.map(function (c) {
            return "<th>" + c + "</th>";
        }).join("") + "</tr></thead><tbody>";
        rows.forEach(function (row) {
            html += "<tr>" + columns.map(function (c) {
                return "<td>" + (row[c] == null ? "" : String(row[c])) + "</td>";
            }).join("") + "</tr>";
        });
        html += "</tbody></table>";
        container.innerHTML = html;
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
        const answerMeta = document.getElementById("answer-meta-" + messageId);
        const resultsDiv = document.getElementById("query-results-" + messageId);
        const errorDiv = document.getElementById("error-card-" + messageId);
        const conversationId = root.dataset.conversationId;

        let aiContent = "";
        let lastSql = "";
        let rowCount = null;
        let tableCount = null;
        contentDiv.classList.add("streaming");
        setWorking(true);

        const eventSource = new EventSource(url);

        function pushStatus(text) {
            if (!statusDiv) return;
            statusDiv.hidden = false;
            const item = document.createElement("li");
            item.textContent = text;
            statusDiv.appendChild(item);
            scrollToBottom();
        }

        function finish() {
            contentDiv.classList.remove("streaming");
            setWorking(false);
        }

        eventSource.onmessage = function (event) {
            const data = JSON.parse(event.data);

            if (data.type === "status") {
                pushStatus(data.content);
            } else if (data.type === "sql") {
                lastSql = data.content || "";
                if (sqlCode) sqlCode.textContent = lastSql;
                if (sqlPanel) sqlPanel.hidden = false;
            } else if (data.type === "rows") {
                rowCount = (data.rows || []).length;
                if (!rowCount) {
                    resultsDiv.innerHTML = '<div class="results-caption">No matching records in the tables you allowed.</div>';
                } else {
                    renderRows(resultsDiv, data.rows);
                }
            } else if (data.type === "unavailable") {
                resultsDiv.innerHTML = '<div class="alert alert-warning">This information is not available from the data you allowed.</div>';
            } else if (data.type === "meta") {
                tableCount = data.tables;
                rowCount = data.rows != null ? data.rows : rowCount;
            } else if (data.type === "token" || data.type === "result") {
                aiContent += data.content;
                contentDiv.textContent = aiContent;
                if (statusDiv) statusDiv.hidden = true;
                scrollToBottom();
            } else if (data.type === "done") {
                eventSource.close();
                finish();
                if (timestampDiv) timestampDiv.textContent = (data.timestamp || "") + " · QueryMind";
                const parts = [];
                if (tableCount != null) parts.push("Used " + tableCount + " table" + (tableCount === 1 ? "" : "s"));
                if (rowCount != null) parts.push(rowCount + " row" + (rowCount === 1 ? "" : "s"));
                if (answerMeta) {
                    answerMeta.textContent = parts.length
                        ? parts.join(" · ") + ". Based on the tables you allowed."
                        : "Based on the tables you allowed.";
                }
                if (lastSql && sqlPanel) sqlPanel.hidden = false;
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
                finish();
                if (lastSql && sqlPanel) sqlPanel.hidden = false;
                const message = String(data.content || "");
                const rawDetail = String(data.detail || "");
                const internal = /JSON serializable|Object of type|Traceback/i.test(message + " " + rawDetail);
                let title = "QueryMind could not finish this answer";
                let detail = "Try asking again in a moment. QueryMind will not invent database results.";
                if (internal) {
                    title = "QueryMind could not display this answer";
                    detail = "The question was understood. Send it again in a moment.";
                } else if (/connection lost|connect/i.test(message)) {
                    title = "Connection lost";
                    detail = "The live answer stream stopped. Send the question again.";
                } else if (/not allowed|permission|unavailable/i.test(message)) {
                    title = "That data is not available";
                    detail = "QueryMind can only use tables you allowed. Change access from Your data if this should be included.";
                }
                if (errorDiv) {
                    errorDiv.hidden = false;
                    const code = data.code || "";
                    if (code === "unavailable" || /not allowed|permission|unavailable/i.test(message)) {
                        title = "That data is not available";
                        detail = "QueryMind can only use tables you allowed. Change access from Your data if this should be included.";
                    } else if (code === "connection_failed" || /connection lost|connect/i.test(message)) {
                        title = "Connection lost";
                        detail = "QueryMind could not reach your database. Check the connection from Your data.";
                    } else if (code === "zero_rows") {
                        title = "No matching records";
                        detail = "The tables you allowed contain no matching rows for this question.";
                    } else if (internal) {
                        title = "QueryMind could not display this answer";
                        detail = "The question was understood. Send it again in a moment.";
                    }
                    let html = errorCardHtml(title, detail);
                    if (rawDetail && !internal) {
                        html += "<details class=\"how-answered\"><summary>Technical detail</summary><pre>" +
                            rawDetail.replace(/[<>]/g, "") + "</pre></details>";
                    }
                    errorDiv.innerHTML = html;
                } else if (!aiContent) {
                    contentDiv.innerHTML = errorCardHtml(title, detail);
                }
            }
        };

        eventSource.onerror = function () {
            eventSource.close();
            finish();
            if (!aiContent && errorDiv) {
                errorDiv.hidden = false;
                errorDiv.innerHTML = errorCardHtml(
                    "Connection lost",
                    "The live answer stream stopped. Send the question again."
                );
            }
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
                if (textarea.value.trim() && form && !textarea.disabled) {
                    form.requestSubmit();
                }
            }
        });
    }

    document.body.addEventListener("htmx:afterSwap", function (event) {
        bootPendingStreams();
        highlightCode();
        scrollToBottom();
        if (textarea && event.detail && event.detail.successful !== false) {
            textarea.value = "";
            resizeComposer();
        }
    });

    document.body.addEventListener("htmx:responseError", function (event) {
        if (!form || event.detail.elt !== form) return;
        setWorking(false);
        if (!hint) return;
        const status = event.detail.xhr && event.detail.xhr.status;
        const text = ((event.detail.xhr && event.detail.xhr.responseText) || "").trim();
        if (status === 400) {
            hint.textContent = text || "Enter a question before sending. Your conversation is unchanged.";
        } else {
            hint.textContent = "QueryMind could not send that question. Your conversation is unchanged.";
        }
    });

    highlightCode();
    scrollToBottom();
    bootPendingStreams();
})();
