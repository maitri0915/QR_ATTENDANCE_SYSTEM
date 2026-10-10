"use strict";

document.addEventListener("DOMContentLoaded", () => {
    initializeAssignmentSearch();
    initializeDashboardCards();
    initializeLiveAttendance();
    initializeStudentDirectory();
    initializeTimetableFilters();
    initializeFacultyLeaveRequests();
    initializePasswordConfirmation();
});

/* Faculty dashboard: search teaching assignments */
function initializeAssignmentSearch() {
    const searchInput = document.querySelector("[data-assignment-search]");
    const cards = document.querySelectorAll(".faculty-assignment-card");

    if (!searchInput || cards.length === 0) return;

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase();

        cards.forEach((card) => {
            const column = card.closest(".col-12, .col-md-6, .col-xl-4");
            const matches = card.textContent.toLowerCase().includes(query);

            if (column) {
                column.hidden = !matches;
            } else {
                card.hidden = !matches;
            }
        });
    });
}

/* Keyboard support for dashboard action cards */
function initializeDashboardCards() {
    document.querySelectorAll(".faculty-action-card").forEach((card) => {
        card.addEventListener("keydown", (event) => {
            if (
                (event.key === "Enter" || event.key === " ") &&
                event.target === card
            ) {
                event.preventDefault();
                card.click();
            }
        });
    });
}

/* Shared location status helper */
function setLocationStatus(message) {
    const status = document.getElementById("status");
    if (status) status.textContent = message;
}


/* Live attendance session */
function initializeLiveAttendance() {
    const page = document.querySelector("[data-live-session-id]");
    if (!page) return;

    const sessionId = page.dataset.liveSessionId;

    if (!sessionId || !/^\d+$/.test(sessionId)) {
        console.error("Invalid live attendance session ID.");
        return;
    }

    const qrImage = document.getElementById("qrImage");
    const placeholder = document.getElementById("qrPlaceholder");
    const tokenElement = document.getElementById("token");
    const copyButton = document.getElementById("copyTokenButton");
    const closeButton = document.getElementById("closeSessionButton");
    const studentList = document.getElementById("studentList");
    const presentCount = document.getElementById("presentCount");
    const timer = document.getElementById("timer");

    if (!qrImage || !tokenElement || !copyButton || !closeButton) {
        console.error("Required live attendance elements are missing.");
        return;
    }

    let sessionClosed = false;
    let qrRequestInProgress = false;
    let attendanceRequestInProgress = false;
    let closeRequestInProgress = false;
    let timerSeconds = 25;

    let qrRefreshInterval = null;
    let attendanceRefreshInterval = null;
    let timerInterval = null;

    function setStatus(message) {
        const status = document.getElementById("qrStatus");
        if (status) status.textContent = message;
    }

    function showPlaceholder(visible, message = "") {
        if (!placeholder) return;

        placeholder.style.display = visible ? "flex" : "none";

        if (message) {
            const text = placeholder.querySelector("p");
            if (text) text.textContent = message;
        }
    }

    async function getJSON(url, options = {}) {
        const response = await fetch(url, {
            credentials: "same-origin",
            cache: "no-store",
            ...options
        });

        let data = {};

        try {
            data = await response.json();
        } catch {
            // The server may return an empty or non-JSON response.
        }

        return { response, data };
    }

    function updateStudents(students) {
        if (!studentList || !Array.isArray(students)) return;

        studentList.replaceChildren();

        if (students.length === 0) {
            const item = document.createElement("li");
            item.className = "live-student-empty";
            item.textContent = "No students present yet.";
            studentList.appendChild(item);
            return;
        }

        students.forEach((student) => {
            const item = document.createElement("li");
            item.className = "live-student-item";

            const avatar = document.createElement("span");
            avatar.className = "live-student-avatar";

            const icon = document.createElement("i");
            icon.className = "bi bi-person-check";
            avatar.appendChild(icon);

            const details = document.createElement("div");
            details.className = "live-student-details";

            const name = document.createElement("strong");
            name.textContent = student.name || "Unnamed Student";

            const rollNumber = document.createElement("span");
            rollNumber.textContent =
                student.roll_number || "No roll number";

            details.append(name, rollNumber);

            const badge = document.createElement("span");
            badge.className = "live-present-badge";
            badge.textContent = "Present";

            item.append(avatar, details, badge);
            studentList.appendChild(item);
        });
    }

    function updateAttendance(data) {
        if (typeof data.present_count === "number" && presentCount) {
            presentCount.textContent = String(data.present_count);
        }

        if (Array.isArray(data.present_students)) {
            updateStudents(data.present_students);
        }
    }

    function updateTimer() {
        if (sessionClosed || !timer) return;

        timer.textContent = timerSeconds > 0
            ? `QR refreshes in ${timerSeconds} seconds`
            : "Refreshing QR code...";

        if (timerSeconds > 0) timerSeconds--;
    }

    async function loadQR() {
        if (sessionClosed || qrRequestInProgress) return;

        qrRequestInProgress = true;

        try {
            const { response, data } = await getJSON(
                `/api/faculty/sessions/${sessionId}/qr`
            );

            if (!response.ok) {
                setStatus(
                    data.error ||
                    data.detail ||
                    "Unable to load the current QR code."
                );
                return;
            }

            if (!data.qr_image || !data.token) {
                setStatus(
                    "The server did not return a QR image or token."
                );
                return;
            }

            qrImage.src = `data:image/png;base64,${data.qr_image}`;
            showPlaceholder(false);
            tokenElement.textContent = data.token;
            copyButton.disabled = false;

            timerSeconds = 25;
            updateTimer();
            updateAttendance(data);

            setStatus("QR code refreshed successfully.");
        } catch (error) {
            setStatus(
                "Unable to connect to the server. Retrying automatically."
            );
            console.error("Load QR error:", error);
        } finally {
            qrRequestInProgress = false;
        }
    }

    async function loadAttendance() {
        if (sessionClosed || attendanceRequestInProgress) return;

        attendanceRequestInProgress = true;

        try {
            const { response, data } = await getJSON(
                `/api/faculty/sessions/${sessionId}/attendance`
            );

            if (!response.ok) {
                if (response.status === 401 || response.status === 403) {
                    setStatus(
                        "Your session may have expired or you may not have access."
                    );
                }
                return;
            }

            updateAttendance(data);
        } catch (error) {
            console.error("Load attendance error:", error);
        } finally {
            attendanceRequestInProgress = false;
        }
    }

    async function copyToken() {
        const token = tokenElement.textContent.trim();

        if (!token || token === "Loading token...") return;

        try {
            if (!navigator.clipboard?.writeText) {
                throw new Error("Clipboard access is unavailable.");
            }

            await navigator.clipboard.writeText(token);
            setStatus("Attendance token copied.");
        } catch {
            setStatus(
                "Copy is unavailable. Select the token and copy it manually."
            );
        }
    }

    async function closeSession() {
        if (sessionClosed || closeRequestInProgress) return;

        const confirmed = window.confirm(
            "Are you sure you want to close this attendance session?\n\n" +
            "Students will no longer be able to mark attendance through it."
        );

        if (!confirmed) return;

        closeRequestInProgress = true;
        closeButton.disabled = true;
        closeButton.innerHTML =
            '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Closing session...';

        try {
            const { response, data } = await getJSON(
                `/api/faculty/sessions/${sessionId}/close`,
                { method: "POST" }
            );

            if (!response.ok) {
                window.alert(
                    data.error ||
                    data.detail ||
                    "Could not close the attendance session."
                );
                return;
            }

            sessionClosed = true;

            clearInterval(qrRefreshInterval);
            clearInterval(attendanceRefreshInterval);
            clearInterval(timerInterval);

            window.alert("Attendance session closed successfully.");
            window.location.href = "/faculty/dashboard";
        } catch (error) {
            window.alert(
                "Could not contact the server. Please try again."
            );
            console.error("Close session error:", error);
        } finally {
            closeRequestInProgress = false;

            if (!sessionClosed) {
                closeButton.disabled = false;
                closeButton.innerHTML =
                    '<i class="bi bi-stop-circle me-2"></i>Close Attendance';
            }
        }
    }

    copyButton.addEventListener("click", copyToken);
    closeButton.addEventListener("click", closeSession);

    showPlaceholder(true, "Loading QR code...");
    copyButton.disabled = true;

    loadQR();
    loadAttendance();

    qrRefreshInterval = setInterval(loadQR, 25000);
    attendanceRefreshInterval = setInterval(loadAttendance, 3000);
    timerInterval = setInterval(updateTimer, 1000);
}

/* Faculty class: student directory search */
function initializeStudentDirectory() {
    const table = document.querySelector("[data-student-directory]");
    const searchInput = document.querySelector("[data-student-search]");
    const countElement = document.querySelector("[data-filtered-student-count]");

    if (!table || !searchInput || !countElement) return;

    const rows = Array.from(table.querySelectorAll("tbody tr"));
    const initialCount = rows.length;

    function updateDirectory() {
        const query = searchInput.value.trim().toLowerCase();
        let visibleCount = 0;

        rows.forEach((row) => {
            const matches = row.textContent.toLowerCase().includes(query);
            row.hidden = !matches;

            if (matches) visibleCount++;
        });

        countElement.textContent =
            `${visibleCount} of ${initialCount} ${
                initialCount === 1 ? "student" : "students"
            } shown`;

        const emptyMessage = document.querySelector(
            "[data-student-search-empty]"
        );

        if (emptyMessage) {
            emptyMessage.hidden = visibleCount !== 0;
        }

        table.hidden = visibleCount === 0;
    }

    searchInput.addEventListener("input", updateDirectory);
    updateDirectory();
}

/* Faculty timetable search and day filter */
function initializeTimetableFilters() {
    const timetable = document.querySelector("[data-faculty-timetable]");
    const searchInput = document.querySelector("[data-timetable-search]");
    const dayFilter = document.querySelector("[data-timetable-day-filter]");
    const countElement = document.querySelector("[data-timetable-filter-count]");
    const noResults = document.querySelector("[data-timetable-no-results]");

    if (!timetable || !searchInput || !dayFilter || !countElement) return;

    const days = Array.from(
        timetable.querySelectorAll("[data-timetable-day]")
    );

    const originalEntries = days.reduce(
        (total, day) =>
            total + day.querySelectorAll("[data-timetable-entry]").length,
        0
    );

    function updateTimetable() {
        const query = searchInput.value.trim().toLowerCase();
        const selectedDay = dayFilter.value;
        let visibleEntries = 0;
        let visibleDays = 0;

        days.forEach((day) => {
            const dayMatches =
                selectedDay === "all" ||
                selectedDay === day.dataset.timetableDay;

            const entries = Array.from(
                day.querySelectorAll("[data-timetable-entry]")
            );

            let dayVisibleEntries = 0;

            entries.forEach((entry) => {
                const matchesSearch =
                    entry.textContent.toLowerCase().includes(query);

                const visible = dayMatches && matchesSearch;
                entry.hidden = !visible;

                if (visible) {
                    dayVisibleEntries++;
                    visibleEntries++;
                }
            });

            const isFreeDay = entries.length === 0;
            const showFreeDay =
                isFreeDay && dayMatches && query === "";

            const showDay =
                dayMatches && (dayVisibleEntries > 0 || showFreeDay);

            day.hidden = !showDay;

            if (showDay) visibleDays++;
        });

        countElement.textContent =
            `Showing ${visibleEntries} of ${originalEntries} scheduled ` +
            `${originalEntries === 1 ? "activity" : "activities"} ` +
            `across ${visibleDays} ${visibleDays === 1 ? "day" : "days"}.`;

        if (noResults) noResults.hidden = visibleDays !== 0;
        timetable.hidden = visibleDays === 0;
    }

    searchInput.addEventListener("input", updateTimetable);
    dayFilter.addEventListener("change", updateTimetable);
    updateTimetable();
}

/* Faculty leave request management */
function initializeFacultyLeaveRequests() {
    const tbody = document.getElementById("leaveList");
    if (!tbody) return;

    const messageBox = document.getElementById("message");
    const searchInput = document.querySelector("[data-leave-search]");
    const statusFilter = document.querySelector("[data-leave-status-filter]");
    const countElement = document.querySelector("[data-leave-count]");
    const noResults = document.querySelector("[data-leave-no-results]");
    const refreshButton = document.querySelector("[data-refresh-leaves]");

    let loading = false;
    let activeDecisionId = null;

    function escapeHTML(value) {
        return String(value ?? "").replace(/[&<>"']/g, (character) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }

    function formatDate(value, includeTime = false) {
        if (!value) return "—";

        const date = new Date(value);

        if (Number.isNaN(date.getTime())) {
            return escapeHTML(value);
        }

        return date.toLocaleString(
            [],
            includeTime
                ? {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                    hour: "2-digit",
                    minute: "2-digit"
                }
                : {
                    day: "2-digit",
                    month: "short",
                    year: "numeric"
                }
        );
    }

    function showMessage(message, success = false) {
        if (!messageBox) return;

        messageBox.className = success
            ? "leave-feedback success"
            : "leave-feedback error";

        messageBox.textContent = message;
        messageBox.hidden = false;
    }

    function clearMessage() {
        if (!messageBox) return;

        messageBox.textContent = "";
        messageBox.hidden = true;
    }

    function statusBadge(status) {
        let label = "Pending";
        let className = "pending";

        if (status === "Approved Leave") {
            label = "Approved";
            className = "approved";
        } else if (status === "Rejected Leave") {
            label = "Rejected";
            className = "rejected";
        }

        return `
            <span class="leave-status-badge ${className}">
                <span class="leave-status-dot"></span>
                ${label}
            </span>
        `;
    }

    function renderRow(leave) {
        const id = Number(leave.id);
        const validId = Number.isSafeInteger(id) && id > 0;
        const pending = leave.status === "Pending Leave";

        const studentCell = `
            <div class="leave-student-cell">
                <span class="person-avatar">
                    <i class="bi bi-person"></i>
                </span>
                <div>
                    <strong>${escapeHTML(leave.student_name || "Unknown Student")}</strong>
                    <span class="leave-secondary-text">
                        Roll No: ${escapeHTML(leave.roll_number || "—")}
                    </span>
                </div>
            </div>
        `;

        const classCell = `
            <div class="leave-class-cell">
                <strong>
                    ${escapeHTML(leave.subject_code || "—")}
                    <span class="timetable-subject-separator">·</span>
                    ${escapeHTML(leave.subject_name || "Unknown Subject")}
                </strong>
                <span class="leave-secondary-text">
                    Division ${escapeHTML(leave.division_name || "—")}
                </span>
                <span class="leave-secondary-text">
                    <i class="bi bi-calendar3 me-1"></i>
                    ${formatDate(leave.lecture_date)}
                </span>
                <span class="leave-secondary-text">
                    <i class="bi bi-clock me-1"></i>
                    ${escapeHTML(leave.start_time || "—")}
                    –
                    ${escapeHTML(leave.end_time || "—")}
                </span>
            </div>
        `;

        const reasonCell = `
            <div class="leave-reason-text">
                ${escapeHTML(leave.reason || "No reason provided.")}
            </div>
        `;

        let actionCell;

        if (pending && validId) {
            actionCell = `
                <div class="leave-action-buttons">
                    <button
                        type="button"
                        class="btn btn-sm btn-success leave-approve-button"
                        data-leave-id="${id}"
                        data-decision="Approved"
                    >
                        <i class="bi bi-check-lg me-1"></i>Approve
                    </button>
                    <button
                        type="button"
                        class="btn btn-sm btn-outline-danger leave-reject-button"
                        data-leave-id="${id}"
                        data-decision="Rejected"
                    >
                        <i class="bi bi-x-lg me-1"></i>Reject
                    </button>
                </div>
            `;
        } else if (pending) {
            actionCell = '<span class="text-muted">Invalid request ID</span>';
        } else {
            actionCell = `
                <div class="leave-reviewed-info">
                    <i class="bi bi-check2-circle me-1"></i>
                    Reviewed
                    <span>${formatDate(leave.reviewed_at, true)}</span>
                </div>
            `;
        }

        return `
            <tr
                data-leave-row
                data-leave-id="${validId ? id : ""}"
                data-leave-status="${escapeHTML(leave.status || "")}"
            >
                <td>${studentCell}</td>
                <td>${classCell}</td>
                <td>${reasonCell}</td>
                <td>${statusBadge(leave.status)}</td>
                <td>${actionCell}</td>
            </tr>
        `;
    }

    function applyFilters() {
        const query = (searchInput?.value || "").trim().toLowerCase();
        const selectedStatus = statusFilter?.value || "all";
        const rows = Array.from(tbody.querySelectorAll("[data-leave-row]"));

        let visibleCount = 0;

        rows.forEach((row) => {
            const matchesSearch =
                row.textContent.toLowerCase().includes(query);

            const matchesStatus =
                selectedStatus === "all" ||
                row.dataset.leaveStatus === selectedStatus;

            const visible = matchesSearch && matchesStatus;
            row.hidden = !visible;

            if (visible) visibleCount++;
        });

        if (countElement) {
            countElement.textContent =
                `Showing ${visibleCount} of ${rows.length} leave requests`;
        }

        if (noResults) {
            noResults.hidden = visibleCount !== 0 || rows.length === 0;
        }

        const table = tbody.closest("table");
        if (table) table.hidden = rows.length > 0 && visibleCount === 0;
    }

    async function readJSON(response) {
        const text = await response.text();
        if (!text) return {};

        try {
            return JSON.parse(text);
        } catch {
            return {
                detail: "The server returned an unexpected response."
            };
        }
    }

    async function loadLeaves() {
        if (loading) return;

        loading = true;
        clearMessage();

        if (refreshButton) {
            refreshButton.disabled = true;
            refreshButton.innerHTML = `
                <span
                    class="spinner-border spinner-border-sm me-1"
                    role="status"
                    aria-hidden="true"
                ></span>
                Loading...
            `;
        }

        try {
            const response = await fetch("/api/faculty/leaves", {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: { "Accept": "application/json" }
            });

            const data = await readJSON(response);

            if (!response.ok) {
                throw new Error(
                    data.detail ||
                    data.error ||
                    "Unable to load leave requests."
                );
            }

            if (!Array.isArray(data.leaves)) {
                throw new Error(
                    "The server response did not contain a valid leave list."
                );
            }

            tbody.innerHTML = data.leaves.length
                ? data.leaves.map(renderRow).join("")
                : `
                    <tr>
                        <td colspan="5">
                            <div class="management-empty">
                                <i class="bi bi-inbox"></i>
                                <h3>No Leave Requests</h3>
                                <p>
                                    There are no student leave requests to review right now.
                                </p>
                            </div>
                        </td>
                    </tr>
                `;

            if (noResults) noResults.hidden = true;

            const table = tbody.closest("table");
            if (table) table.hidden = false;

            applyFilters();
        } catch (error) {
            console.error("Failed to load leave requests:", error);
            showMessage(
                error.message || "Server error while loading leave requests."
            );

            tbody.innerHTML = `
                <tr>
                    <td colspan="5">
                        <div class="management-empty">
                            <i class="bi bi-cloud-slash"></i>
                            <h3>Unable to Load Requests</h3>
                            <p>
                                Check your connection and try refreshing the requests.
                            </p>
                        </div>
                    </td>
                </tr>
            `;

            if (countElement) {
                countElement.textContent = "Unable to load requests.";
            }

            if (noResults) noResults.hidden = true;
        } finally {
            loading = false;

            if (refreshButton) {
                refreshButton.disabled = false;
                refreshButton.innerHTML =
                    '<i class="bi bi-arrow-clockwise me-1"></i>Refresh';
            }
        }
    }

    async function decideLeave(id, decision, button) {
        if (activeDecisionId !== null || loading) return;

        if (!Number.isSafeInteger(id) || id <= 0) {
            showMessage("Invalid leave request ID.");
            return;
        }

        if (decision !== "Approved" && decision !== "Rejected") {
            showMessage("Invalid leave decision.");
            return;
        }

        const action = decision === "Approved" ? "approve" : "reject";
        const confirmed = window.confirm(
            `Are you sure you want to ${action} this leave request?`
        );

        if (!confirmed) return;

        const row = button.closest("tr");
        if (!row) return;

        activeDecisionId = id;

        const buttons = Array.from(row.querySelectorAll("button"));
        const originalHTML = button.innerHTML;

        buttons.forEach((item) => {
            item.disabled = true;
        });

        button.innerHTML = `
            <span
                class="spinner-border spinner-border-sm me-1"
                role="status"
                aria-hidden="true"
            ></span>
            Processing...
        `;

        let successMessage = "";

        try {
            const response = await fetch(
                `/api/faculty/leaves/${id}/decision`,
                {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    body: JSON.stringify({ status: decision })
                }
            );

            const data = await readJSON(response);

            if (!response.ok) {
                throw new Error(
                    data.detail ||
                    data.error ||
                    "Could not update the leave request."
                );
            }

            successMessage =
                data.message || `Leave request ${action}d successfully.`;

            await loadLeaves();
            showMessage(successMessage, true);
        } catch (error) {
            console.error("Leave decision error:", error);
            showMessage(
                error.message || "Server error. Please try again."
            );

            buttons.forEach((item) => {
                item.disabled = false;
            });

            button.innerHTML = originalHTML;
        } finally {
            activeDecisionId = null;
        }
    }

    tbody.addEventListener("click", (event) => {
        const target = event.target;
        if (!(target instanceof Element)) return;

        const button = target.closest("button[data-leave-id]");
        if (!button || !tbody.contains(button)) return;

        decideLeave(
            Number(button.dataset.leaveId),
            button.dataset.decision,
            button
        );
    });

    searchInput?.addEventListener("input", applyFilters);
    statusFilter?.addEventListener("change", applyFilters);
    refreshButton?.addEventListener("click", loadLeaves);

    loadLeaves();
}

/* Faculty registration: confirm password */
function initializePasswordConfirmation() {
    const form = document.querySelector(
        ".auth-faculty form[data-prevent-double-submit]"
    );

    if (!form) return;

    const password = form.querySelector("[data-faculty-password]");
    const confirmation = form.querySelector("[data-password-confirm]");
    const message = form.querySelector("[data-password-match-message]");

    if (!password || !confirmation) return;

    function validatePasswordMatch() {
        const bothFilled =
            password.value !== "" && confirmation.value !== "";

        const matches = password.value === confirmation.value;

        confirmation.setCustomValidity(
            bothFilled && !matches ? "Passwords do not match." : ""
        );

        if (!message) return;

        if (!confirmation.value) {
            message.textContent = "Enter the same password in both fields.";
            message.removeAttribute("data-match");
        } else if (matches) {
            message.textContent = "Passwords match.";
            message.dataset.match = "true";
        } else {
            message.textContent = "Passwords do not match.";
            message.dataset.match = "false";
        }
    }

    password.addEventListener("input", validatePasswordMatch);
    confirmation.addEventListener("input", validatePasswordMatch);

    form.addEventListener("submit", (event) => {
        validatePasswordMatch();

        if (!form.checkValidity()) {
            event.preventDefault();
            form.reportValidity();
        }
    });
}