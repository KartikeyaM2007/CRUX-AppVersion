document.addEventListener("DOMContentLoaded", () => {
    const pages = Array.from(document.querySelectorAll(".page"));
    const routeTriggers = Array.from(document.querySelectorAll("[data-route]"));
    const navLinks = Array.from(document.querySelectorAll(".nav-center a"));
    const mobileMenu = document.getElementById("mobile-menu");
    const hamburger = document.getElementById("hamburger");
    const infoModal = document.getElementById("info-modal");
    const toastStack = document.getElementById("toast-stack");
    const outputs = {
        generation: document.getElementById("generation-output"),
        repair: document.getElementById("repair-output"),
        cleaning: document.getElementById("cleaning-output")
    };
    const compares = {
        generation: document.querySelector('[data-compare="generation"]'),
        repair: document.querySelector('[data-compare="repair"]'),
        cleaning: document.querySelector('[data-compare="cleaning"]')
    };
    const chatState = {
        uploaded: false,
        uploadedName: "",
        lastIntent: ""
    };
    const generationState = {
        query: "No generation request entered yet.",
        interpretation: "The generator will infer schema from the uploaded or sample CSV."
    };
    const generationChatPlan = {
        fileName: "",
        intent: "",
        rowTarget: "",
        intel: null
    };
    const intelState = {
        generation: {
            query: generationState.query,
            problem: "Create synthetic private rows from the active CSV.",
            understood: "Upload a CSV or choose a template to populate schema understanding.",
            expected: "A synthetic CSV trained on repaired local data."
        },
        repair: {
            query: "Repair broken values in the active CSV.",
            problem: "Choose a sample or upload a CSV to inspect missing values, dates, IDs, products, and numeric anomalies.",
            understood: "No CSV inspected yet.",
            expected: "A repaired CSV with fewer blanks, normalized labels, and corrected amount-like values."
        },
        cleaning: {
            query: "Clean the active CSV before repair or generation.",
            problem: "Upload a CSV or use mock data to inspect duplicates, whitespace, dates, and blanks.",
            understood: "No CSV inspected yet.",
            expected: "A cleaner CSV with trimmed strings, parsed values, and duplicate rows removed."
        }
    };
    let pendingGenerationTemplate = "";
    const workflowTimers = {};

    function escapeHtml(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function setRoute(route, options = {}) {
        const pageId = route || "home";
        pages.forEach(page => page.classList.toggle("active", page.id === pageId));
        navLinks.forEach(link => link.classList.toggle("active", link.dataset.route === pageId));
        mobileMenu.classList.remove("open");
        if (location.hash.replace("#", "") !== pageId) {
            history.pushState(null, "", pageId === "home" ? "#home" : `#${pageId}`);
        }
        const target = options.scrollTarget ? document.getElementById(options.scrollTarget) : null;
        window.setTimeout(() => {
            if (target) {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            } else {
                window.scrollTo({ top: 0, behavior: "smooth" });
            }
        }, 40);
    }

    routeTriggers.forEach(trigger => {
        trigger.addEventListener("click", event => {
            event.preventDefault();
            setRoute(trigger.dataset.route, { scrollTarget: trigger.dataset.scrollTarget });
        });
    });

    hamburger.addEventListener("click", () => {
        mobileMenu.classList.toggle("open");
    });

    function openInfoModal() {
        if (!infoModal) return;
        infoModal.classList.add("open");
        infoModal.setAttribute("aria-hidden", "false");
    }

    function closeInfoModal() {
        if (!infoModal) return;
        infoModal.classList.remove("open");
        infoModal.setAttribute("aria-hidden", "true");
    }

    document.querySelectorAll("#info-button, #mobile-info-button").forEach(button => {
        button.addEventListener("click", openInfoModal);
    });

    document.querySelectorAll("[data-info-close]").forEach(button => {
        button.addEventListener("click", closeInfoModal);
    });

    window.addEventListener("keydown", event => {
        if (event.key === "Escape") closeInfoModal();
    });

    window.addEventListener("popstate", () => {
        setRoute(location.hash.replace("#", "") || "home");
    });

    setRoute(location.hash.replace("#", "") || "home");

    function terminalEl(scope) {
        return document.querySelector(`[data-terminal="${scope}"] .terminal-lines`);
    }

    function clearTerminal(scope) {
        const target = terminalEl(scope);
        if (!target) return;
        target.innerHTML = "";
        writeTerminal(scope, "Ready.", "success");
        writeTerminal(scope, "Hows your day", "info");
    }

    function writeTerminal(scope, message, level = "info", extraClass = "") {
        const target = terminalEl(scope);
        if (!target) return;
        const line = document.createElement("span");
        line.className = `terminal-line ${extraClass}`.trim();
        line.innerHTML = `<span class="prompt">PS C:\\Crux\\${escapeHtml(scope)}&gt;</span> <span class="level-${escapeHtml(level)}">${escapeHtml(message)}</span>`;
        target.appendChild(line);
        target.scrollTop = target.scrollHeight;
    }

    function workflowEl(type) {
        return document.querySelector(`[data-workflow="${type}"]`);
    }

    function setWorkflowStep(type, index, done = false) {
        const workflow = workflowEl(type);
        if (!workflow) return;
        workflow.querySelectorAll("[data-step]").forEach(node => {
            const step = Number(node.dataset.step);
            node.classList.toggle("step-active", step === index && !done);
            node.classList.toggle("step-done", step < index || (done && step <= index));
        });
        workflow.querySelectorAll("[data-line]").forEach(line => {
            const lineIndex = Number(line.dataset.line);
            line.classList.toggle("line-active", lineIndex === index - 1 && !done);
            line.classList.toggle("line-done", lineIndex < index - 1 || (done && lineIndex <= index - 1));
        });
    }

    function resetWorkflow(type) {
        const workflow = workflowEl(type);
        if (!workflow) return;
        window.clearInterval(workflowTimers[type]);
        workflow.classList.remove("workflow-running");
        workflow.querySelectorAll(".step-active, .step-done").forEach(node => node.classList.remove("step-active", "step-done"));
        workflow.querySelectorAll(".line-active, .line-done").forEach(line => line.classList.remove("line-active", "line-done"));
    }

    function startWorkflow(type) {
        const workflow = workflowEl(type);
        if (!workflow) return;
        resetWorkflow(type);
        workflow.classList.add("workflow-running");
        let step = 0;
        setWorkflowStep(type, step);
        workflowTimers[type] = window.setInterval(() => {
            step = Math.min(step + 1, 3);
            setWorkflowStep(type, step);
            if (step === 3) {
                step = 0;
            }
        }, 900);
    }

    function finishWorkflow(type) {
        const workflow = workflowEl(type);
        if (!workflow) return;
        window.clearInterval(workflowTimers[type]);
        workflow.classList.remove("workflow-running");
        setWorkflowStep(type, 3, true);
    }

    function renderLogs(scope, logs = [], reset = false) {
        const target = terminalEl(scope);
        if (!target) return;
        if (reset) target.innerHTML = "";
        const fragment = document.createDocumentFragment();
        logs.forEach(entry => {
            const line = document.createElement("span");
            const level = entry.level || "info";
            line.className = "terminal-line";
            line.innerHTML = `<span class="prompt">PS C:\\Crux\\${escapeHtml(scope)}&gt;</span> <span class="level-${escapeHtml(level)}">[${escapeHtml(entry.time || "--:--:--")}] ${escapeHtml(entry.message)}</span>`;
            fragment.appendChild(line);
        });
        target.appendChild(fragment);
        target.scrollTop = target.scrollHeight;
    }

    ["agent", "generation", "repair", "cleaning"].forEach(clearTerminal);

    function setOutput(type, html, loading = false) {
        const target = outputs[type];
        if (!target) return;
        target.classList.toggle("loading", loading);
        target.innerHTML = html;
    }

    function showToast(title, message, level = "success") {
        if (!toastStack) return;
        const toast = document.createElement("div");
        toast.className = `task-toast ${level}`.trim();
        const icon = level === "error" ? "fa-circle-exclamation" : level === "info" ? "fa-circle-info" : "fa-circle-check";
        toast.innerHTML = `<i class="fa-solid ${icon}"></i><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(message)}</span></div>`;
        toastStack.appendChild(toast);
        window.setTimeout(() => {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(-8px)";
            window.setTimeout(() => toast.remove(), 240);
        }, 4200);
    }

    async function parseJsonResponse(response) {
        const text = await response.text();
        let data;
        try {
            data = text ? JSON.parse(text) : {};
        } catch {
            data = {
                status: "error",
                message: text ? text.slice(0, 500) : `HTTP ${response.status} ${response.statusText}`
            };
        }
        if (!response.ok || data.status === "error") {
            const error = new Error(data.message || "Request failed.");
            error.logs = data.logs || [];
            throw error;
        }
        return data;
    }

    async function postJson(url) {
        const response = await fetch(url, { method: "POST" });
        return parseJsonResponse(response);
    }

    async function postJsonBody(url, body) {
        const response = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body)
        });
        return parseJsonResponse(response);
    }

    function activeTool() {
        const activePage = document.querySelector(".page.active");
        return activePage && activePage.id !== "home" ? activePage.id : "generation";
    }

    function renderDownload(url, label) {
        return url ? `<a href="${escapeHtml(url)}">${escapeHtml(label)}</a>` : "";
    }

    function updateGenerationViews() {
        const queryView = document.getElementById("generation-query-view");
        const interpretationView = document.getElementById("generation-interpretation-view");
        if (queryView) queryView.textContent = generationState.query;
        if (interpretationView) interpretationView.textContent = generationState.interpretation;
    }

    function renderIntel(type) {
        const panel = document.querySelector(`[data-intel="${type}"]`);
        const intel = intelState[type];
        if (!panel || !intel) return;
        panel.querySelectorAll("[data-intel-field]").forEach(field => {
            const key = field.dataset.intelField;
            field.textContent = intel[key] || "Waiting for dataset context.";
        });
        if (type === "generation") {
            updateGenerationViews();
        }
    }

    function updateIntel(type, intel = {}) {
        if (!intelState[type]) return;
        intelState[type] = { ...intelState[type], ...intel };
        if (type === "generation") {
            generationState.query = intelState.generation.query || generationState.query;
            generationState.interpretation = intelState.generation.problem || generationState.interpretation;
        }
        renderIntel(type);
    }

    function applyIntelPayload(payload, preferredType = activeTool()) {
        if (!payload) return;
        if (payload.generation || payload.repair || payload.cleaning) {
            ["generation", "repair", "cleaning"].forEach(type => {
                if (payload[type]) updateIntel(type, payload[type]);
            });
            return;
        }
        updateIntel(preferredType, payload);
    }

    async function setGenerationQuery(query) {
        generationState.query = query || "Generate synthetic data matching the uploaded dataset.";
        generationState.interpretation = "Interpreting request against current dataset...";
        updateGenerationViews();
        const data = await postJsonBody("/api/generation-query", { query: generationState.query });
        generationState.query = data.query;
        generationState.interpretation = data.interpretation;
        updateIntel("generation", {
            ...(data.intel || {}),
            query: data.query,
            problem: data.interpretation
        });
        updateGenerationViews();
        writeTerminal("generation", `User query: ${data.query}`, "success");
        writeTerminal("generation", `Model interpretation: ${data.interpretation}`, "info");
        return data;
    }

    function addGenerationChatActions(message, actions = []) {
        if (!generationChatLog) return;
        const bubble = createChatBubble(message, "bot", actions);
        generationChatLog.appendChild(bubble);
        generationChatLog.scrollTop = generationChatLog.scrollHeight;
    }

    function generationIntelFromUpload(data) {
        return (data && data.intel && (data.intel.generation || data.intel)) || null;
    }

    function summarizeUploadedDataset(intel, fileName) {
        const stats = intel?.stats || {};
        const understood = intel?.understood || "I inspected the uploaded CSV.";
        return `I analyzed ${fileName}. ${understood} I need two choices before generation: what should the new rows emphasize, and how many rows should I create?`;
    }

    async function confirmGenerationPlan() {
        const fileName = generationChatPlan.fileName || chatState.uploadedName || "the uploaded CSV";
        const focus = generationChatPlan.intent || "same structure, clean synthetic rows";
        const rows = generationChatPlan.rowTarget || "same row count as the repaired source";
        const query = `Generate ${rows} from ${fileName}. Focus: ${focus}. Keep the uploaded schema, regenerate IDs/dates, remove missing values, keep amount-like values positive, and preserve the source distribution.`;
        await setGenerationQuery(query);
        addGenerationChatActions(`Ready. I interpreted this as: ${generationState.interpretation} Start the real CTGAN generation now?`, [
            { label: "Generate now", run: () => runFeature("generation") },
            { label: "Edit query", run: () => generationChatInput && generationChatInput.focus() }
        ]);
    }

    function askGenerationRowCount() {
        addGenerationChatActions("How many synthetic rows should I generate from this CSV?", [
            {
                label: "Same row count",
                run: async () => {
                    generationChatPlan.rowTarget = "the same number of rows as the uploaded CSV";
                    await confirmGenerationPlan();
                }
            },
            {
                label: "1,000 rows",
                run: async () => {
                    generationChatPlan.rowTarget = "1000 rows";
                    await confirmGenerationPlan();
                }
            },
            {
                label: "10,000 rows",
                run: async () => {
                    generationChatPlan.rowTarget = "10000 rows";
                    await confirmGenerationPlan();
                }
            }
        ]);
    }

    function startGenerationFollowups(data, fileName) {
        const intel = generationIntelFromUpload(data);
        generationChatPlan.fileName = fileName || chatState.uploadedName || "uploaded CSV";
        generationChatPlan.intent = "";
        generationChatPlan.rowTarget = "";
        generationChatPlan.intel = intel;
        addGenerationChat(summarizeUploadedDataset(intel, generationChatPlan.fileName), "bot");
        addGenerationChatActions("What should the synthetic dataset emphasize?", [
            {
                label: "Same structure",
                run: () => {
                    generationChatPlan.intent = "same schema and distributions as the uploaded CSV";
                    askGenerationRowCount();
                }
            },
            {
                label: "Clean financial data",
                run: () => {
                    generationChatPlan.intent = "clean financial transaction rows with no blanks or negative amount-like values";
                    askGenerationRowCount();
                }
            },
            {
                label: "Fraud / review cases",
                run: () => {
                    generationChatPlan.intent = "fraud-review or Needs Review cases while keeping rare cases realistic";
                    askGenerationRowCount();
                }
            }
        ]);
    }

    function renderSummary(type, data) {
        const before = data.before || {};
        const after = data.after || {};
        const rows = data.rows || after.rows || 0;
        const parts = [
            ["Status", data.message || "Completed"],
            ["Rows", rows],
            ["Missing before", before.missing ?? "n/a"],
            ["Missing after", after.missing ?? "n/a"],
            ["Duplicates after", after.duplicates ?? "n/a"],
            ["Terminal logs", (data.logs || []).length]
        ];
        if (data.evaluation && data.evaluation.numerical) {
            const passCount = data.evaluation.numerical.filter(item => item.status === "PASS").length;
            parts.push(["KS checks passed", `${passCount}/${data.evaluation.numerical.length}`]);
        }
        if (data.training) {
            parts.push(["CTGAN trained rows", data.training.training_rows ?? "n/a"]);
        }
        if (data.quality) {
            parts.push(["Schema match", data.quality.same_columns ? "yes" : "no"]);
            parts.push(["Synthetic overlap", `${data.quality.sample_row_overlap_pct ?? 0}%`]);
            parts.push(["Generated missing", data.quality.missing_values ?? "n/a"]);
            parts.push(["Generated negatives", data.quality.negative_amounts ?? "n/a"]);
        }
        const html = `<div class="summary-list">${parts.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>${renderDownload(data.download_url, `Download ${type} CSV`)}`;
        setOutput(type, html);
    }

    function statRows(stats = {}) {
        const rows = [
            ["Rows", stats.rows],
            ["Columns", stats.columns],
            ["Missing", stats.missing],
            ["Duplicates", stats.duplicates]
        ];
        if (stats.negative_amounts !== undefined) rows.push(["Negative amounts", stats.negative_amounts]);
        if (stats.category_nulls !== undefined) rows.push(["Category nulls", stats.category_nulls]);
        if (stats.avg_amount !== undefined) rows.push(["Avg amount", stats.avg_amount]);
        return rows.filter(([, value]) => value !== undefined);
    }

    function metricList(stats) {
        return `<div class="metric-list">${statRows(stats).map(([label, value]) => `<div class="metric-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>`;
    }

    function bars(before = {}, after = {}) {
        const values = [
            ["Missing", before.missing || 0, after.missing || 0],
            ["Duplicates", before.duplicates || 0, after.duplicates || 0],
            ["Negative", before.negative_amounts || 0, after.negative_amounts || 0]
        ];
        const max = Math.max(1, ...values.flatMap(item => [item[1], item[2]]));
        return values.map(([label, beforeValue, afterValue]) => {
            const beforeWidth = Math.max(2, (beforeValue / max) * 100);
            const afterWidth = Math.max(2, (afterValue / max) * 100);
            return `<div class="bar-row"><span><b>${escapeHtml(label)} before</b><em>${escapeHtml(beforeValue)}</em></span><div class="bar-track"><i style="width:${beforeWidth}%"></i></div></div>
                    <div class="bar-row"><span><b>${escapeHtml(label)} after</b><em>${escapeHtml(afterValue)}</em></span><div class="bar-track"><i style="width:${afterWidth}%"></i></div></div>`;
        }).join("");
    }

    function sampleTable(rows = [], columns = []) {
        if (!rows.length) return "<div class=\"compare-empty\">No sample rows yet.</div>";
        const visibleColumns = (columns.length ? columns : Object.keys(rows[0])).slice(0, 6);
        return `<div class="sample-table-wrap"><table class="sample-table"><thead><tr>${visibleColumns.map(col => `<th>${escapeHtml(col)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${visibleColumns.map(col => `<td>${escapeHtml(row[col])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }

    function changedFields(before = {}, after = {}) {
        return Object.keys(after).filter(key => String(before[key] ?? "") !== String(after[key] ?? ""));
    }

    function sampleChangeItems(data) {
        const beforeRows = data.before_sample || [];
        const afterRows = data.after_sample || [];
        const count = Math.min(3, Math.max(beforeRows.length, afterRows.length));
        const items = [];
        for (let index = 0; index < count; index += 1) {
            const before = beforeRows[index] || {};
            const after = afterRows[index] || {};
            const changes = changedFields(before, after);
            const rowLabel = `row ${index + 1}`;
            if (!Object.keys(before).length && Object.keys(after).length) {
                items.push(`${rowLabel}: created -> ${JSON.stringify(after)}`);
            } else if (!changes.length) {
                items.push(`${rowLabel}: inspected, no visible sample change`);
            } else {
                const summary = changes.slice(0, 4).map(field => `${field}: "${before[field] ?? ""}" -> "${after[field] ?? ""}"`).join("; ");
                items.push(`${rowLabel}: ${summary}`);
            }
        }
        return items;
    }

    function sampleChangePanel(data) {
        const items = sampleChangeItems(data);
        if (!items.length) return "";
        return `<div class="sample-change-panel">
            <h3>Sample changes</h3>
            ${items.map(item => `<div>${escapeHtml(item)}</div>`).join("")}
        </div>`;
    }

    function renderComparison(type, data) {
        const target = compares[type];
        if (!target) return;
        const beforeStats = data.before || {};
        const afterStats = data.after || {};
        const beforeRows = data.before_sample || [];
        const afterRows = data.after_sample || [];
        target.innerHTML = `<h2>Before vs After</h2>
            ${sampleChangePanel(data)}
            <div class="compare-grid">
                <div class="compare-side">
                    <h3>Before</h3>
                    ${metricList(beforeStats)}
                    ${sampleTable(beforeRows, data.columns || [])}
                </div>
                <div class="compare-side">
                    <h3>After</h3>
                    ${metricList(afterStats)}
                    ${bars(beforeStats, afterStats)}
                    ${sampleTable(afterRows, data.columns || [])}
                </div>
            </div>`;
    }

    function renderTerminalSamples(type, data) {
        const items = sampleChangeItems(data);
        if (!items.length) return;
        writeTerminal(type, "Before vs after sample:", "success", "terminal-sample");
        items.forEach(item => {
            writeTerminal(type, item, item.includes("no visible") ? "info" : "success", "terminal-sample");
        });
    }

    function renderMockPreview(scope, data) {
        setOutput(scope, `<div class="summary-list"><div><span>Status</span><strong>${escapeHtml(data.message)}</strong></div><div><span>Rows</span><strong>${escapeHtml(data.after?.rows || 0)}</strong></div><div><span>Missing values</span><strong>${escapeHtml(data.after?.missing || 0)}</strong></div><div><span>Path</span><strong>${escapeHtml(data.path)}</strong></div></div>`);
        const compareData = {
            before: {},
            after: data.after,
            before_sample: [],
            after_sample: data.after_sample,
            columns: data.columns
        };
        renderComparison(scope, compareData);
    }

    async function runMock(scope = activeTool(), options = {}) {
        const reset = options.reset !== false;
        if (reset) clearTerminal(scope);
        showToast("Sample task started", `Creating mock data for ${scope}.`, "info");
        writeTerminal(scope, "Sample test started.", "success");
        writeTerminal(scope, "Creating dirty financial CSV.", "info");
        setOutput(scope, "<div class=\"summary-list\"><div><span>Status</span><strong>Creating sample data</strong></div></div>", true);
        const data = await postJson("/api/generate-mock");
        applyIntelPayload(data.intel, scope);
        renderLogs(scope, data.logs || [], false);
        renderMockPreview(scope, data);
        showToast("Sample task complete", `Mock data is ready for ${scope}.`, "success");
        return data;
    }

    async function runFeature(type, options = {}) {
        const endpoints = {
            cleaning: "/api/run-cleaning",
            repair: "/api/run-repair",
            generation: "/api/run-generation"
        };
        const labels = {
            cleaning: "Data cleaning started.",
            repair: "Data repair started.",
            generation: "Data generation started."
        };
        if (type === "generation") {
            updateGenerationViews();
        }
        showToast(`${type[0].toUpperCase() + type.slice(1)} started`, labels[type], "info");
        if (options.sample) {
            await runMock(type, { reset: true });
            writeTerminal(type, `Sample ready. ${labels[type]}`, "success");
        } else {
            clearTerminal(type);
            writeTerminal(type, labels[type], "success");
        }
        startWorkflow(type);
        setOutput(type, `<div class="summary-list"><div><span>Status</span><strong>${escapeHtml(labels[type])}</strong></div><div><span>Backend</span><strong>running</strong></div></div>`, true);
        try {
            const data = await postJson(endpoints[type]);
            applyIntelPayload(data.intel, type);
            renderLogs(type, data.logs || [], false);
            renderTerminalSamples(type, data);
            renderSummary(type, data);
            renderComparison(type, data);
            finishWorkflow(type);
            showToast(`${type[0].toUpperCase() + type.slice(1)} complete`, data.message || "Task completed successfully.", "success");
            return data;
        } catch (error) {
            resetWorkflow(type);
            if (error.logs) renderLogs(type, error.logs, false);
            writeTerminal(type, error.message, "error");
            setOutput(type, `<div class="summary-list"><div><span>Error</span><strong>${escapeHtml(error.message)}</strong></div></div>`);
            showToast(`${type[0].toUpperCase() + type.slice(1)} failed`, error.message, "error");
            throw error;
        }
    }

    const actionMap = {
        mock: () => runMock(activeTool()),
        cleaning: () => runFeature("cleaning"),
        repair: () => runFeature("repair"),
        generation: () => runFeature("generation"),
        "sample-cleaning": () => runFeature("cleaning", { sample: true }),
        "sample-repair": () => runFeature("repair", { sample: true }),
        "sample-generation": () => runFeature("generation", { sample: true })
    };

    function setActionButtonsDisabled(disabled) {
        document.querySelectorAll("[data-action]").forEach(button => {
            button.disabled = disabled;
        });
    }

    document.querySelectorAll("[data-action]").forEach(button => {
        button.addEventListener("click", async () => {
            const action = actionMap[button.dataset.action];
            if (!action) return;
            const original = button.innerHTML;
            setActionButtonsDisabled(true);
            button.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>Working';
            try {
                await action();
            } catch (error) {
                const type = activeTool();
                writeTerminal(type, error.message, "error");
            } finally {
                setActionButtonsDisabled(false);
                button.innerHTML = original;
            }
        });
    });

    document.querySelectorAll("[data-upload-zone]").forEach(zone => {
        const input = zone.querySelector("input");

        zone.addEventListener("click", event => {
            if (event.target !== input) input.click();
        });

        zone.addEventListener("dragover", event => {
            event.preventDefault();
            zone.classList.add("dragover");
        });

        zone.addEventListener("dragleave", () => zone.classList.remove("dragover"));

        zone.addEventListener("drop", event => {
            event.preventDefault();
            zone.classList.remove("dragover");
            const file = event.dataTransfer.files[0];
            if (file) uploadFile(file, activeTool());
        });

        input.addEventListener("change", event => {
            const file = event.target.files[0];
            if (file) uploadFile(file, activeTool());
        });
    });

    async function uploadFile(file, scope = activeTool()) {
        if (!file.name.toLowerCase().endsWith(".csv")) {
            alert("Please upload a CSV file.");
            return null;
        }

        clearTerminal(scope);
        writeTerminal(scope, `Uploading ${file.name}.`, "success");
        const formData = new FormData();
        formData.append("file", file);

        try {
            const response = await fetch("/api/upload", { method: "POST", body: formData });
            const data = await parseJsonResponse(response);
            renderLogs(scope, data.logs || [], false);
            applyIntelPayload(data.intel, scope);
            chatState.uploaded = true;
            chatState.uploadedName = file.name;
            if (outputs[scope]) {
                setOutput(scope, `<div class="summary-list"><div><span>Status</span><strong>${escapeHtml(data.message)}</strong></div><div><span>Rows</span><strong>${escapeHtml(data.after?.rows || 0)}</strong></div><div><span>File</span><strong>${escapeHtml(file.name)}</strong></div></div>`);
                renderComparison(scope, { after: data.after, after_sample: data.after_sample, columns: data.columns });
            }
            if (scope === "generation") {
                startGenerationFollowups(data, file.name);
            }
            return data;
        } catch (error) {
            writeTerminal(scope, error.message, "error");
            if (outputs[scope]) setOutput(scope, `<div class="summary-list"><div><span>Error</span><strong>${escapeHtml(error.message)}</strong></div></div>`);
            return null;
        }
    }

    const chatLog = document.getElementById("chat-log");
    const chatForm = document.getElementById("chat-form");
    const chatInput = document.getElementById("chat-input");
    const chatPanel = document.querySelector("[data-chat-drop]");
    const chatFileInput = document.getElementById("chat-file-input");
    const sharedChatLogs = [
        chatLog,
        document.getElementById("shared-generation-chat-log"),
        document.getElementById("repair-chat-log"),
        document.getElementById("cleaning-chat-log")
    ].filter(Boolean);
    const sharedChatForms = [
        { form: chatForm, input: chatInput },
        { form: document.getElementById("shared-generation-chat-form"), input: document.getElementById("shared-generation-chat-input") },
        { form: document.getElementById("repair-chat-form"), input: document.getElementById("repair-chat-input") },
        { form: document.getElementById("cleaning-chat-form"), input: document.getElementById("cleaning-chat-input") }
    ].filter(item => item.form && item.input);
    const generationChatLog = document.getElementById("generation-chat-log");
    const generationChatForm = document.getElementById("generation-chat-form");
    const generationChatInput = document.getElementById("generation-chat-input");
    const generationChatUpload = document.getElementById("generation-chat-upload");
    const generationChatFileInput = document.getElementById("generation-chat-file-input");

    function createChatBubble(message, who = "bot", actions = []) {
        const bubble = document.createElement("div");
        bubble.className = `chat-message ${who}`;
        bubble.innerHTML = escapeHtml(message);
        if (actions.length) {
            const actionWrap = document.createElement("div");
            actionWrap.className = "chat-actions";
            actions.forEach(action => {
                const button = document.createElement("button");
                button.className = "btn btn-outline";
                button.type = "button";
                button.textContent = action.label;
                button.addEventListener("click", action.run);
                actionWrap.appendChild(button);
            });
            bubble.appendChild(actionWrap);
        }
        return bubble;
    }

    function addChat(message, who = "bot", actions = []) {
        sharedChatLogs.forEach(log => {
            log.appendChild(createChatBubble(message, who, actions));
            log.scrollTop = log.scrollHeight;
        });
    }

    function syncSharedChatWindows() {
        if (!chatLog || !sharedChatLogs.length) return;
        sharedChatLogs.forEach(log => {
            if (log !== chatLog) log.innerHTML = chatLog.innerHTML;
            log.dataset.synced = "true";
        });
    }

    function addGenerationChat(message, who = "bot") {
        if (!generationChatLog) return;
        const bubble = document.createElement("div");
        bubble.className = `chat-message ${who}`;
        bubble.innerHTML = escapeHtml(message);
        generationChatLog.appendChild(bubble);
        generationChatLog.scrollTop = generationChatLog.scrollHeight;
    }

    async function loadRepairSample(sampleId) {
        clearTerminal("repair");
        writeTerminal("repair", `Loading repair sample: ${sampleId}`, "success");
        showToast("Repair sample loading", "Preparing faulty CSV sample.", "info");
        try {
            const data = await postJson(`/api/use-repair-sample/${sampleId}`);
            applyIntelPayload(data.intel, "repair");
            renderLogs("repair", data.logs || [], false);
            chatState.uploaded = true;
            chatState.uploadedName = `${data.sample?.name || sampleId}.csv`;
            setRoute("repair");
            setOutput("repair", `<div class="summary-list"><div><span>Status</span><strong>${escapeHtml(data.message)}</strong></div><div><span>Problem</span><strong>${escapeHtml(data.sample?.description || "")}</strong></div><div><span>Expected</span><strong>${escapeHtml(data.sample?.expected || "")}</strong></div><div><span>Rows</span><strong>${escapeHtml(data.after?.rows || 0)}</strong></div></div>`);
            renderComparison("repair", { after: data.after, after_sample: data.after_sample, columns: data.columns });
            addChat(`Loaded repair sample "${data.sample?.name || sampleId}". I can run repair when you confirm.`, "bot", [
                { label: "Run repair", run: () => runFromChat("repair", false) },
                { label: "Preview only", run: () => writeTerminal("agent", "Repair sample loaded for preview only.", "info") }
            ]);
            showToast("Repair sample loaded", data.sample?.name || sampleId, "success");
        } catch (error) {
            writeTerminal("repair", error.message, "error");
            showToast("Sample load failed", error.message, "error");
        }
    }

    function detectIntent(text) {
        const value = text.toLowerCase();
        if (/(generate|synthetic|create|make|financial|fraud|sample data|new rows)/.test(value)) return "generation";
        if (/(repair|fix|broken|null|missing category|llama|ollama|infer)/.test(value)) return "repair";
        if (/(clean|dedupe|duplicate|normalize|trim|date|missing number|preprocess)/.test(value)) return "cleaning";
        return "";
    }

    async function runFromChat(type, sample = false) {
        chatState.lastIntent = type;
        const label = type === "generation" ? "generation" : type === "repair" ? "repair" : "cleaning";
        addChat(`Routing to ${label} and starting the run.`, "bot");
        writeTerminal("agent", `Routing user to ${label}.`, "success");
        if (type === "generation") {
            await setGenerationQuery(generationState.query === "No generation request entered yet." ? "Generate financial synthetic data from the current dataset." : generationState.query);
        }
        setRoute(type);
        try {
            await runFeature(type, { sample });
            writeTerminal("agent", `${label} completed.`, "success");
        } catch (error) {
            writeTerminal("agent", error.message, "error");
            addChat(`The ${label} run hit an error: ${error.message}`, "bot");
        }
    }

    function askUploadedFollowup() {
        addChat(`I loaded ${chatState.uploadedName}. What should I do with it?`, "bot", [
            { label: "Clean data", run: () => runFromChat("cleaning", false) },
            { label: "Repair data", run: () => runFromChat("repair", false) },
            { label: "Generate synthetic data", run: () => runFromChat("generation", false) }
        ]);
    }

    async function handleSharedChatSubmit(text) {
        if (!text) return;
        addChat(text, "user");
        writeTerminal("agent", `User request: ${text}`, "info");
        const intent = detectIntent(text);
        if (intent === "generation") {
            generationState.query = text;
            updateGenerationViews();
        }

        if (!intent) {
            addChat("I need one more choice: generation, repair, or cleaning.", "bot", [
                { label: "Generation", run: () => runFromChat("generation", !chatState.uploaded) },
                { label: "Repair", run: () => runFromChat("repair", !chatState.uploaded) },
                { label: "Cleaning", run: () => runFromChat("cleaning", !chatState.uploaded) }
            ]);
            return;
        }

        if (chatState.uploaded && (intent === "cleaning" || intent === "repair")) {
            addChat("I have your CSV. Before I run it, choose the exact operation so the output page matches the job.", "bot", [
                { label: "Clean only", run: () => runFromChat("cleaning", false) },
                { label: "Repair missing values", run: () => runFromChat("repair", false) },
                { label: "Generate after repair", run: () => runFromChat("generation", false) }
            ]);
            return;
        }

        const sample = !chatState.uploaded;
        if (sample) {
            addChat("No uploaded CSV is active, so I will run the built-in sample test.", "bot");
        }
        await runFromChat(intent, sample);
    }

    sharedChatForms.forEach(({ form, input }) => {
        form.addEventListener("submit", async event => {
            event.preventDefault();
            const text = input.value.trim();
            input.value = "";
            await handleSharedChatSubmit(text);
        });
    });

    chatPanel.addEventListener("click", event => {
        if (event.target.closest(".chat-dropzone")) chatFileInput.click();
    });

    chatPanel.addEventListener("dragover", event => {
        event.preventDefault();
        chatPanel.classList.add("dragover");
    });

    chatPanel.addEventListener("dragleave", () => chatPanel.classList.remove("dragover"));

    chatPanel.addEventListener("drop", async event => {
        event.preventDefault();
        chatPanel.classList.remove("dragover");
        const file = event.dataTransfer.files[0];
        if (!file) return;
        addChat(`Uploaded ${file.name}`, "user");
        const data = await uploadFile(file, "agent");
        if (data) askUploadedFollowup();
    });

    chatFileInput.addEventListener("change", async event => {
        const file = event.target.files[0];
        if (!file) return;
        addChat(`Uploaded ${file.name}`, "user");
        const data = await uploadFile(file, "agent");
        if (data) askUploadedFollowup();
    });

    if (generationChatUpload && generationChatFileInput) {
        const openGenerationFilePicker = () => generationChatFileInput.click();
        generationChatUpload.addEventListener("click", openGenerationFilePicker);
        generationChatUpload.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openGenerationFilePicker();
            }
        });
        generationChatUpload.addEventListener("dragover", event => {
            event.preventDefault();
            generationChatUpload.classList.add("dragover");
        });
        generationChatUpload.addEventListener("dragleave", () => generationChatUpload.classList.remove("dragover"));
        generationChatUpload.addEventListener("drop", async event => {
            event.preventDefault();
            generationChatUpload.classList.remove("dragover");
            const file = event.dataTransfer.files[0];
            if (!file) return;
            addGenerationChat(`Uploaded ${file.name}`, "user");
            await uploadFile(file, "generation");
        });
        generationChatFileInput.addEventListener("change", async event => {
            const file = event.target.files[0];
            if (!file) return;
            addGenerationChat(`Uploaded ${file.name}`, "user");
            await uploadFile(file, "generation");
        });
    }

    if (generationChatForm) {
        generationChatForm.addEventListener("submit", async event => {
            event.preventDefault();
            const text = generationChatInput.value.trim();
            if (!text) return;
            generationChatInput.value = "";
            addGenerationChat(text, "user");
            try {
                const data = await setGenerationQuery(text);
                addGenerationChatActions(`Got it. ${data.interpretation} Should I generate from the active CSV now?`, [
                    { label: "Generate now", run: () => runFeature("generation") },
                    { label: "Upload CSV first", run: () => generationChatFileInput && generationChatFileInput.click() }
                ]);
            } catch (error) {
                addGenerationChat(`I could not interpret that yet: ${error.message}`, "bot");
            }
        });
    }

    document.querySelectorAll("[data-generation-template]").forEach(button => {
        button.addEventListener("click", async () => {
            const prompt = button.dataset.generationTemplate;
            pendingGenerationTemplate = prompt;
            setRoute("generation");
            if (generationChatInput) generationChatInput.value = prompt;
            addGenerationChat(prompt, "user");
            try {
                const data = await setGenerationQuery(prompt);
                addGenerationChatActions(`Template loaded. ${data.interpretation} Proceed with generation?`, [
                    { label: "Proceed", run: () => runFeature("generation") },
                    { label: "Edit first", run: () => generationChatInput && generationChatInput.focus() }
                ]);
                addChat(`Generation template loaded: ${prompt}`, "bot", [
                    { label: "Proceed with generation", run: () => runFeature("generation") },
                    { label: "Open generation", run: () => setRoute("generation") }
                ]);
                showToast("Template loaded", "Confirm in the generation chatbot to proceed.", "success");
            } catch (error) {
                addGenerationChat(`Template could not be loaded: ${error.message}`, "bot");
                showToast("Template failed", error.message, "error");
            }
        });
    });

    document.querySelectorAll("[data-repair-sample]").forEach(button => {
        button.addEventListener("click", () => loadRepairSample(button.dataset.repairSample));
    });

    syncSharedChatWindows();
    ["generation", "repair", "cleaning"].forEach(renderIntel);
    updateGenerationViews();
});
