
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    initializeStudentAttendance();
    initializeStudentLeave();
    initializeStudentMark();
    initializeStudentRegistration();
});

/* ============================================================
   SHARED HELPERS
   ============================================================ */

function studentEscape(value) {
    const element = document.createElement("div");
    element.textContent = value == null ? "" : String(value);
    return element.innerHTML;
}

function studentNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
}

function studentPercentage(value) {
    if (value === null || value === undefined || value === "") {
        return null;
    }

    const number = Number(value);

    if (!Number.isFinite(number)) {
        return null;
    }

    return Math.max(0, Math.min(100, number));
}

function studentFormatDate(value, includeTime = false) {
    if (!value) {
        return "-";
    }

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return studentEscape(value);
    }

    const options = {
        day: "2-digit",
        month: "short",
        year: "numeric"
    };

    if (includeTime) {
        options.hour = "2-digit";
        options.minute = "2-digit";
    }

    return studentEscape(date.toLocaleString([], options));
}

async function studentReadResponse(response) {
    return response.json().catch(() => ({}));
}

function studentShowTableMessage(tbody, columns, message) {
    if (!tbody) {
        return;
    }

    const row = document.createElement("tr");
    const cell = document.createElement("td");

    cell.colSpan = columns;
    cell.className = "attendance-empty-cell";
    cell.textContent = message;

    row.appendChild(cell);
    tbody.replaceChildren(row);
}


/* ============================================================
   1. STUDENT ATTENDANCE PAGE
   Route: /student/attendance
   API:   GET /api/student/attendance
   ============================================================ */

function initializeStudentAttendance() {
    const overallElement = document.getElementById("overall");
    const subjectsElement = document.getElementById("subjects");
    const historyElement = document.getElementById("history");

    // This script may be included on every student page.
    // Run this initializer only on the attendance page.
    if (!overallElement || !subjectsElement || !historyElement) {
        return;
    }

    let loading = false;

    function attendanceBar(percentage) {
        const value = studentPercentage(percentage);

        if (value === null) {
            return `
                <span class="attendance-no-data">
                    No classes yet
                </span>
            `;
        }

        const low = value < 75;

        return `
            <div class="attendance-progress-group">
                <div
                    class="attendance-progress ${
                        low
                            ? "attendance-progress-low"
                            : "attendance-progress-good"
                    }"
                    role="progressbar"
                    aria-label="Attendance percentage"
                    aria-valuenow="${value}"
                    aria-valuemin="0"
                    aria-valuemax="100"
                    title="${value}% attendance; 75% required"
                >
                    <span style="width: ${value}%"></span>
                    <span
                        class="attendance-target-marker"
                        aria-hidden="true"
                    ></span>
                </div>

                <strong class="attendance-percentage ${
                    low ? "text-danger" : "text-success"
                }">
                    ${value}%
                </strong>
            </div>
        `;
    }

    function attendanceNote(item) {
        if (studentPercentage(item.percentage) === null) {
            return `
                <span class="attendance-no-data">
                    Not available yet
                </span>
            `;
        }

        if (item.warning) {
            const needed = Math.max(
                0,
                studentNumber(item.classes_needed)
            );

            return `
                <span class="attendance-recommendation attendance-recommendation-low">
                    <i class="bi bi-exclamation-circle me-1"></i>
                    Attend the next ${needed}
                    ${needed === 1 ? "class" : "classes"}
                </span>
            `;
        }

        const canMiss = Math.max(0, studentNumber(item.can_miss));

        return `
            <span class="attendance-recommendation attendance-recommendation-good">
                <i class="bi bi-check-circle me-1"></i>
                Can miss ${canMiss}
                ${canMiss === 1 ? "class" : "classes"}
            </span>
        `;
    }

    function statusBadge(status, leaveStatus) {
        if (status === "present") {
            return `
                <span class="attendance-status-badge attendance-status-present">
                    <i class="bi bi-check-circle-fill"></i>
                    Present
                </span>
            `;
        }

        if (status === "leave") {
            return `
                <span class="attendance-status-badge attendance-status-leave">
                    <i class="bi bi-calendar-check-fill"></i>
                    Leave approved
                </span>
            `;
        }

        if (leaveStatus === "Pending Leave") {
            return `
                <div class="attendance-status-stack">
                    <span class="attendance-status-badge attendance-status-absent">
                        Absent
                    </span>

                    <span class="attendance-status-badge attendance-status-pending">
                        Leave pending
                    </span>
                </div>
            `;
        }

        if (leaveStatus === "Rejected Leave") {
            return `
                <div class="attendance-status-stack">
                    <span class="attendance-status-badge attendance-status-absent">
                        Absent
                    </span>

                    <span class="attendance-status-badge attendance-status-rejected">
                        Leave rejected
                    </span>
                </div>
            `;
        }

        return `
            <span class="attendance-status-badge attendance-status-absent">
                <i class="bi bi-x-circle-fill"></i>
                Absent
            </span>
        `;
    }

    function overallBanner(overall) {
        const percentage = studentPercentage(overall.percentage);

        if (percentage === null) {
            return `
                <div class="attendance-message attendance-message-info">
                    <i class="bi bi-info-circle-fill"></i>
                    <span>
                        No completed attendance sessions are available yet.
                        Your summary will appear after sessions are closed.
                    </span>
                </div>
            `;
        }

        if (overall.warning) {
            const needed = Math.max(
                0,
                studentNumber(overall.classes_needed)
            );

            return `
                <div class="attendance-message attendance-message-warning">
                    <i class="bi bi-exclamation-triangle-fill"></i>

                    <div>
                        <strong>Your attendance is below 75%.</strong>
                        <p>
                            Your current attendance is ${percentage}%.
                            Attend the next ${needed}
                            ${needed === 1 ? "class" : "classes"}
                            consecutively to reach 75%, according to the current calculation.
                        </p>
                    </div>
                </div>
            `;
        }

        const canMiss = Math.max(0, studentNumber(overall.can_miss));

        return `
            <div class="attendance-message attendance-message-success">
                <i class="bi bi-check-circle-fill"></i>

                <div>
                    <strong>Your attendance meets the 75% requirement.</strong>
                    <p>
                        You can miss up to ${canMiss}
                        ${canMiss === 1 ? "more class" : "more classes"}
                        and remain at or above 75%, based on the current calculation.
                    </p>
                </div>
            </div>
        `;
    }

    function renderOverall(overall) {
        const percentage = studentPercentage(overall.percentage);
        const label = percentage === null ? "--" : `${percentage}%`;
        const progress = percentage === null ? 0 : percentage;

        overallElement.innerHTML = `
            <div class="attendance-overview-header">
                <div>
                    <span class="section-label">ATTENDANCE SUMMARY</span>
                    <h2>Overall Attendance</h2>
                    <p>Your attendance across completed sessions.</p>
                </div>

                <div class="attendance-overview-icon">
                    <i class="bi bi-pie-chart-fill"></i>
                </div>
            </div>

            <div class="attendance-overview-main">
                <div class="attendance-overview-score">
                    <span class="attendance-score-label">
                        Overall percentage
                    </span>

                    <strong class="attendance-score-value">${label}</strong>

                    <div
                        class="attendance-overview-progress"
                        role="progressbar"
                        aria-label="Overall attendance"
                        aria-valuenow="${progress}"
                        aria-valuemin="0"
                        aria-valuemax="100"
                    >
                        <span style="width: ${progress}%"></span>
                    </div>

                    <span class="attendance-score-caption">
                        Required attendance: 75%
                    </span>
                </div>

                <div class="attendance-overview-stats">
                    <div class="attendance-stat-card">
                        <span class="attendance-stat-icon">
                            <i class="bi bi-journal-check"></i>
                        </span>
                        <span class="attendance-stat-label">Sessions</span>
                        <strong>${studentEscape(studentNumber(overall.total))}</strong>
                    </div>

                    <div class="attendance-stat-card">
                        <span class="attendance-stat-icon attendance-stat-present">
                            <i class="bi bi-check-circle"></i>
                        </span>
                        <span class="attendance-stat-label">Present</span>
                        <strong>${studentEscape(studentNumber(overall.present))}</strong>
                    </div>

                    <div class="attendance-stat-card">
                        <span class="attendance-stat-icon attendance-stat-absent">
                            <i class="bi bi-x-circle"></i>
                        </span>
                        <span class="attendance-stat-label">Absent</span>
                        <strong>${studentEscape(studentNumber(overall.absent))}</strong>
                    </div>

                    <div class="attendance-stat-card">
                        <span class="attendance-stat-icon attendance-stat-leave">
                            <i class="bi bi-calendar-check"></i>
                        </span>
                        <span class="attendance-stat-label">Excused leave</span>
                        <strong>${studentEscape(studentNumber(overall.leave))}</strong>
                    </div>
                </div>
            </div>

            ${overallBanner(overall)}
        `;
    }

    function renderSubjects(subjects) {
        if (!Array.isArray(subjects) || subjects.length === 0) {
            subjectsElement.innerHTML = `
                <tr>
                    <td colspan="6" class="attendance-empty-cell">
                        <i class="bi bi-journal-x"></i>
                        <strong>No subject records yet</strong>
                        <span>
                            Subject attendance will appear after sessions are completed.
                        </span>
                    </td>
                </tr>
            `;
            return;
        }

        subjectsElement.innerHTML = subjects.map(subject => `
            <tr>
                <td>
                    <div class="attendance-subject-name">
                        <span class="attendance-subject-icon">
                            <i class="bi bi-book"></i>
                        </span>

                        <div>
                            <strong>${studentEscape(subject.subject_code)}</strong>
                            <span>${studentEscape(subject.subject_name)}</span>
                        </div>
                    </div>
                </td>

                <td>
                    <span class="attendance-count attendance-count-present">
                        ${studentEscape(studentNumber(subject.present))}
                    </span>
                </td>

                <td>
                    <span class="attendance-count attendance-count-absent">
                        ${studentEscape(studentNumber(subject.absent))}
                    </span>
                </td>

                <td>
                    <span class="attendance-count attendance-count-leave">
                        ${studentEscape(studentNumber(subject.leave))}
                    </span>
                </td>

                <td>${attendanceBar(subject.percentage)}</td>
                <td>${attendanceNote(subject)}</td>
            </tr>
        `).join("");
    }

    function renderHistory(records) {
        if (!Array.isArray(records) || records.length === 0) {
            historyElement.innerHTML = `
                <tr>
                    <td colspan="5" class="attendance-empty-cell">
                        <i class="bi bi-clock-history"></i>
                        <strong>No attendance history yet</strong>
                        <span>
                            Your completed attendance sessions will appear here.
                        </span>
                    </td>
                </tr>
            `;
            return;
        }

        historyElement.innerHTML = records.map(record => {
            const canApplyForLeave =
                record.status === "absent" &&
                !record.leave_status &&
                record.session_id !== null &&
                record.session_id !== undefined &&
                String(record.session_id) !== "";

            const action = canApplyForLeave
                ? `
                    <a
                        class="attendance-leave-link"
                        href="/student/leave?session=${encodeURIComponent(String(record.session_id))}"
                    >
                        <i class="bi bi-calendar-plus me-1"></i>
                        Apply for leave
                    </a>
                `
                : '<span class="attendance-no-action">—</span>';

            return `
                <tr>
                    <td>
                        <span class="attendance-history-date">
                            <i class="bi bi-calendar3 me-2"></i>
                            ${studentFormatDate(record.date, true)}
                        </span>
                    </td>

                    <td>
                        <div class="attendance-subject-name">
                            <div>
                                <strong>${studentEscape(record.subject_code)}</strong>
                                <span>${studentEscape(record.subject_name)}</span>
                            </div>
                        </div>
                    </td>

                    <td>${statusBadge(record.status, record.leave_status)}</td>

                    <td>
                        <span class="attendance-method">
                            ${studentEscape(record.method || "-")}
                        </span>
                    </td>

                    <td>${action}</td>
                </tr>
            `;
        }).join("");
    }

    function showAttendanceError(message, needsLogin = false) {
        overallElement.innerHTML = `
            <div class="attendance-load-error">
                <i class="bi ${
                    needsLogin ? "bi-shield-lock" : "bi-cloud-slash"
                }"></i>

                <strong>
                    ${needsLogin
                        ? "Your session may have expired."
                        : "Unable to load attendance"}
                </strong>

                <p>${studentEscape(message)}</p>

                ${
                    needsLogin
                        ? `
                            <a href="/student/login" class="btn student-primary-btn">
                                Sign in
                            </a>
                        `
                        : `
                            <button
                                type="button"
                                class="btn student-primary-btn"
                                data-retry-attendance
                            >
                                <i class="bi bi-arrow-clockwise me-2"></i>
                                Try Again
                            </button>
                        `
                }
            </div>
        `;

        studentShowTableMessage(
            subjectsElement,
            6,
            "Attendance data could not be loaded."
        );

        studentShowTableMessage(
            historyElement,
            5,
            "Attendance history could not be loaded."
        );
    }

    async function loadAttendance() {
        if (loading) {
            return;
        }

        loading = true;

        const retryButton = overallElement.querySelector(
            "[data-retry-attendance]"
        );

        if (retryButton) {
            retryButton.disabled = true;
        }

        try {
            const response = await fetch("/api/student/attendance", {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" }
            });

            if (response.status === 401 || response.status === 403) {
                showAttendanceError(
                    "Please sign in again to view your attendance.",
                    true
                );
                return;
            }

            if (!response.ok) {
                throw new Error("Unable to retrieve attendance records.");
            }

            const data = await studentReadResponse(response);

            if (
                !data ||
                !data.overall ||
                !Array.isArray(data.subjects) ||
                !Array.isArray(data.history)
            ) {
                throw new Error("The attendance response has an unexpected format.");
            }

            renderOverall(data.overall);
            renderSubjects(data.subjects);
            renderHistory(data.history);

        } catch (error) {
            console.error("Attendance loading failed:", error);
            showAttendanceError(
                "Please check your connection and try again."
            );
        } finally {
            loading = false;
        }
    }

    overallElement.addEventListener("click", event => {
        const button = event.target.closest("[data-retry-attendance]");

        if (button) {
            loadAttendance();
        }
    });

    loadAttendance();
}


/* ============================================================
   2. STUDENT LEAVE PAGE
   Routes:
   GET  /api/student/leave/eligible
   GET  /api/student/leave
   POST /api/student/leave
   ============================================================ */

function initializeStudentLeave() {
    const form = document.getElementById("leaveForm");
    const lectureSelect = document.getElementById("lecture");
    const reasonInput = document.getElementById("reason");
    const submitButton = document.getElementById("submitBtn");
    const messageBox = document.getElementById("message");
    const leaveList = document.getElementById("leaveList");
    const refreshButton = document.getElementById("refreshLeavesBtn");
    const reasonCounter = document.getElementById("reasonCounter");

    if (
        !form ||
        !lectureSelect ||
        !reasonInput ||
        !submitButton ||
        !messageBox ||
        !leaveList ||
        !refreshButton ||
        !reasonCounter
    ) {
        return;
    }

    let submitting = false;
    let loadingEligible = false;
    let loadingLeaves = false;

    function showMessage(message, success = false) {
        messageBox.hidden = false;
        messageBox.className = success
            ? "leave-form-message leave-message-success"
            : "leave-form-message leave-message-error";

        const icon = document.createElement("i");
        icon.className = success
            ? "bi bi-check-circle-fill"
            : "bi bi-exclamation-circle-fill";

        const content = document.createElement("span");
        content.textContent = message;

        messageBox.replaceChildren(icon, content);
    }

    function clearMessage() {
        messageBox.hidden = true;
        messageBox.textContent = "";
        messageBox.className = "leave-form-message";
    }

    function updateSubmitState() {
        submitButton.disabled =
            submitting ||
            loadingEligible ||
            !lectureSelect.value ||
            !reasonInput.value.trim() ||
            reasonInput.value.trim().length > 500;
    }

    function updateReasonCounter() {
        reasonCounter.textContent = `${reasonInput.value.length} / 500`;
        updateSubmitState();
    }

    function leaveBadge(status) {
        if (status === "Approved Leave") {
            return `
                <span class="attendance-status-badge attendance-status-present">
                    <i class="bi bi-check-circle-fill"></i>
                    Approved
                </span>
            `;
        }

        if (status === "Rejected Leave") {
            return `
                <span class="attendance-status-badge attendance-status-rejected">
                    <i class="bi bi-x-circle-fill"></i>
                    Rejected
                </span>
            `;
        }

        return `
            <span class="attendance-status-badge attendance-status-pending">
                <i class="bi bi-hourglass-split"></i>
                Pending
            </span>
        `;
    }

    async function loadEligible() {
        if (loadingEligible || submitting) {
            return;
        }

        loadingEligible = true;
        lectureSelect.disabled = true;
        updateSubmitState();

        lectureSelect.replaceChildren();

        const loadingOption = document.createElement("option");
        loadingOption.value = "";
        loadingOption.textContent = "Loading eligible classes...";
        lectureSelect.appendChild(loadingOption);

        try {
            const response = await fetch(
                "/api/student/leave/eligible",
                {
                    method: "GET",
                    credentials: "same-origin",
                    headers: { Accept: "application/json" }
                }
            );

            if (response.status === 401 || response.status === 403) {
                throw new Error("Your session may have expired. Please sign in again.");
            }

            if (!response.ok) {
                throw new Error("Unable to load eligible classes.");
            }

            const data = await studentReadResponse(response);
            const lectures = Array.isArray(data.lectures)
                ? data.lectures
                : [];

            lectureSelect.replaceChildren();

            const placeholder = document.createElement("option");
            placeholder.value = "";

            if (!lectures.length) {
                placeholder.textContent = "No upcoming classes available";
                lectureSelect.appendChild(placeholder);
                return;
            }

            placeholder.textContent = "Choose an upcoming class";
            lectureSelect.appendChild(placeholder);

            lectures.forEach(lecture => {
                const option = document.createElement("option");
                option.value = String(lecture.timetable_id ?? "");
                option.dataset.date = String(lecture.lecture_date ?? "");

                const dateText = lecture.lecture_date
                    ? new Date(`${lecture.lecture_date}T00:00:00`)
                        .toLocaleDateString([], {
                            day: "2-digit",
                            month: "short",
                            year: "numeric"
                        })
                    : "Date unavailable";

                const timeText =
                    `${lecture.start_time || ""} – ${lecture.end_time || ""}`;

                const subjectText =
                    `${lecture.subject_code || ""} - ${lecture.subject_name || ""}`;

                const facultyText = lecture.faculty_name
                    ? ` · ${lecture.faculty_name}`
                    : "";

                option.textContent =
                    `${dateText} · ${timeText} · ${subjectText}${facultyText}`;

                lectureSelect.appendChild(option);
            });

        } catch (error) {
            console.error("Failed to load eligible classes:", error);

            lectureSelect.replaceChildren();

            const option = document.createElement("option");
            option.value = "";
            option.textContent = "Unable to load classes";
            lectureSelect.appendChild(option);

            showMessage(
                error.message ||
                "Upcoming classes could not be loaded. Please try again.",
                false
            );
        } finally {
            loadingEligible = false;
            lectureSelect.disabled =
                lectureSelect.options.length <= 1 &&
                lectureSelect.options[0]?.textContent ===
                    "No upcoming classes available";

            // If loading failed, keep the select disabled.
            if (
                lectureSelect.options[0]?.textContent ===
                "Unable to load classes"
            ) {
                lectureSelect.disabled = true;
            }

            updateSubmitState();
        }
    }

    async function loadLeaves() {
        if (loadingLeaves) {
            return;
        }

        loadingLeaves = true;
        refreshButton.disabled = true;

        try {
            const response = await fetch("/api/student/leave", {
                method: "GET",
                credentials: "same-origin",
                headers: { Accept: "application/json" }
            });

            if (response.status === 401 || response.status === 403) {
                throw new Error("Your session may have expired. Please sign in again.");
            }

            if (!response.ok) {
                throw new Error("Unable to load leave history.");
            }

            const data = await studentReadResponse(response);
            const leaves = Array.isArray(data.leaves) ? data.leaves : [];

            if (!leaves.length) {
                leaveList.innerHTML = `
                    <tr>
                        <td colspan="4" class="attendance-empty-cell">
                            <i class="bi bi-calendar2-x"></i>
                            <strong>No leave requests yet</strong>
                            <span>Your submitted requests will appear here.</span>
                        </td>
                    </tr>
                `;
                return;
            }

            leaveList.innerHTML = leaves.map(leave => `
                <tr>
                    <td>
                        <div class="leave-history-class">
                            <strong>
                                ${studentEscape(leave.subject_code)} -
                                ${studentEscape(leave.subject_name)}
                            </strong>

                            <span>
                                <i class="bi bi-calendar3 me-1"></i>
                                ${studentFormatDate(leave.lecture_date)}
                            </span>

                            <span>
                                <i class="bi bi-clock me-1"></i>
                                ${studentEscape(leave.start_time || "")} –
                                ${studentEscape(leave.end_time || "")}
                            </span>

                            ${
                                leave.faculty_name
                                    ? `
                                        <span>
                                            <i class="bi bi-person me-1"></i>
                                            ${studentEscape(leave.faculty_name)}
                                        </span>
                                    `
                                    : ""
                            }
                        </div>
                    </td>

                    <td>
                        <div class="leave-history-reason">
                            ${studentEscape(leave.reason)}
                        </div>
                    </td>

                    <td>${leaveBadge(leave.status)}</td>

                    <td>
                        <span class="leave-submitted-date">
                            ${studentFormatDate(leave.submitted_at, true)}
                        </span>
                    </td>
                </tr>
            `).join("");

        } catch (error) {
            console.error("Failed to load leave history:", error);

            studentShowTableMessage(
                leaveList,
                4,
                error.message || "Unable to load leave requests. Please refresh."
            );
        } finally {
            loadingLeaves = false;
            refreshButton.disabled = false;
        }
    }

    async function submitLeave() {
        if (submitting) {
            return;
        }

        clearMessage();

        const selectedOption =
            lectureSelect.options[lectureSelect.selectedIndex];

        const timetableId = lectureSelect.value;
        const lectureDate = selectedOption?.dataset.date || "";
        const reason = reasonInput.value.trim();

        if (!timetableId) {
            showMessage("Please choose an upcoming class.");
            return;
        }

        if (!lectureDate) {
            showMessage("The lecture date could not be determined.");
            return;
        }

        if (!reason) {
            showMessage("Please enter a reason for your leave request.");
            reasonInput.focus();
            return;
        }

        if (reason.length > 500) {
            showMessage("Your reason must not exceed 500 characters.");
            reasonInput.focus();
            return;
        }

        submitting = true;
        submitButton.innerHTML = `
            <span
                class="spinner-border spinner-border-sm me-2"
                role="status"
            ></span>
            Submitting...
        `;
        updateSubmitState();

        let succeeded = false;

        try {
            const response = await fetch("/api/student/leave", {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    Accept: "application/json"
                },
                body: JSON.stringify({
                    timetable_id: Number(timetableId),
                    lecture_date: lectureDate,
                    reason
                })
            });

            const data = await studentReadResponse(response);

            if (response.status === 401 || response.status === 403) {
                showMessage("Your session may have expired. Please sign in again.");
                return;
            }

            if (!response.ok) {
                showMessage(
                    typeof data.detail === "string"
                        ? data.detail
                        : "Failed to submit your leave request."
                );
                return;
            }

            succeeded = true;
            reasonInput.value = "";
            updateReasonCounter();

            showMessage(
                data.message ||
                "Your leave request was submitted successfully.",
                true
            );

        } catch (error) {
            console.error("Leave submission failed:", error);

            showMessage(
                "A network or server error occurred. Please try again."
            );
        } finally {
            submitting = false;

            submitButton.innerHTML = `
                <i class="bi bi-send me-2"></i>
                Submit Leave Request
            `;

            updateSubmitState();
        }

        if (succeeded) {
            await Promise.allSettled([
                loadEligible(),
                loadLeaves()
            ]);
        }
    }

    lectureSelect.addEventListener("change", () => {
        clearMessage();
        updateSubmitState();
    });

    reasonInput.addEventListener("input", () => {
        clearMessage();
        updateReasonCounter();
    });

    refreshButton.addEventListener("click", loadLeaves);

    form.addEventListener("submit", event => {
        event.preventDefault();
        submitLeave();
    });

    updateReasonCounter();
    loadEligible();
    loadLeaves();
}


/* ============================================================
   3. STUDENT MARK ATTENDANCE PAGE
   API: POST /api/student/attendance/mark
   Requires the html5-qrcode library on this page.
   ============================================================ */

function initializeStudentMark() {
    const statusBox = document.getElementById("status");
    const statusHeading = document.getElementById("statusHeading");
    const statusIcon = document.getElementById("statusIcon");
    const statusPanel = document.getElementById("statusPanel");

    const startButton = document.getElementById("startScanBtn");
    const stopButton = document.getElementById("stopScanBtn");
    const tokenInput = document.getElementById("token");
    const manualButton = document.getElementById("manualBtn");
    const manualForm = document.getElementById("manualTokenForm");

    if (
        !statusBox ||
        !statusHeading ||
        !statusIcon ||
        !statusPanel ||
        !startButton ||
        !stopButton ||
        !tokenInput ||
        !manualButton ||
        !manualForm
    ) {
        return;
    }

    let scanner = null;
    let scannerStarting = false;
    let scannerStopping = false;
    let processing = false;
    let lastToken = "";
    let lastAttempt = 0;

    function setStatus(heading, message, type = "info") {
        statusHeading.textContent = heading;
        statusBox.textContent = message;
        statusPanel.className = "attendance-status-panel";

        if (type === "success") {
            statusPanel.classList.add("attendance-status-success");
            statusIcon.innerHTML = '<i class="bi bi-check-circle-fill"></i>';
        } else if (type === "error") {
            statusPanel.classList.add("attendance-status-error");
            statusIcon.innerHTML = '<i class="bi bi-exclamation-circle-fill"></i>';
        } else if (type === "loading") {
            statusPanel.classList.add("attendance-status-loading");
            statusIcon.innerHTML = `
                <span
                    class="spinner-border spinner-border-sm"
                    role="status"
                ></span>
            `;
        } else {
            statusIcon.innerHTML = '<i class="bi bi-info-circle-fill"></i>';
        }
    }

    function updateButtons() {
        const busy = processing || scannerStarting || scannerStopping;

        startButton.hidden = Boolean(scanner) || scannerStarting;
        stopButton.hidden = !scanner || scannerStarting;

        startButton.disabled = busy;
        stopButton.disabled = busy;
        manualButton.disabled = busy;
        tokenInput.disabled = processing;
    }

    function locationErrorMessage(error) {
        if (error && typeof error.code === "number") {
            if (error.code === 1) {
                return "Location access was denied. Allow location permission and try again.";
            }

            if (error.code === 2) {
                return "Your location could not be determined. Check your device's location settings.";
            }

            if (error.code === 3) {
                return "The location request timed out. Please try again.";
            }
        }

        return error?.message ||
            "A network or server error occurred. Please try again.";
    }

    function getCurrentPosition() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(
                    new Error("Location services are not supported by this browser.")
                );
                return;
            }

            navigator.geolocation.getCurrentPosition(
                resolve,
                reject,
                {
                    enableHighAccuracy: true,
                    timeout: 15000,
                    maximumAge: 0
                }
            );
        });
    }

    async function stopScanner() {
        if (!scanner || scannerStopping || scannerStarting) {
            return;
        }

        scannerStopping = true;
        updateButtons();

        const activeScanner = scanner;

        try {
            await activeScanner.stop();
        } catch (error) {
            console.warn("Scanner stop notice:", error);
        }

        try {
            activeScanner.clear();
        } catch (error) {
            console.warn("Scanner cleanup notice:", error);
        }

        if (scanner === activeScanner) {
            scanner = null;
        }

        scannerStopping = false;
        updateButtons();
    }

    async function markAttendance(token, manual = false) {
        token = String(token || "").trim();

        if (!token) {
            setStatus(
                "Token required",
                "Please scan a QR code or enter an attendance token.",
                "error"
            );
            return;
        }

        if (processing || scannerStarting || scannerStopping) {
            return;
        }

        if (
            !manual &&
            token === lastToken &&
            Date.now() - lastAttempt < 5000
        ) {
            return;
        }

        lastToken = token;
        lastAttempt = Date.now();

        processing = true;
        updateButtons();

        setStatus(
            "Checking location",
            "Please allow location access so your attendance can be verified.",
            "loading"
        );

        let attendanceSucceeded = false;

        try {
            const position = await getCurrentPosition();

            setStatus(
                "Verifying attendance",
                "Checking your token, class session, and location...",
                "loading"
            );

            const response = await fetch(
                "/api/student/attendance/mark",
                {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "Content-Type": "application/json",
                        Accept: "application/json"
                    },
                    body: JSON.stringify({
                        token,
                        latitude: position.coords.latitude,
                        longitude: position.coords.longitude
                    })
                }
            );

            const result = await studentReadResponse(response);

            if (response.status === 401 || response.status === 403) {
                setStatus(
                    "Sign-in required",
                    "Your session may have expired. Please sign in again.",
                    "error"
                );
                return;
            }

            if (!response.ok) {
                setStatus(
                    "Attendance not marked",
                    typeof result.detail === "string"
                        ? result.detail
                        : "Attendance could not be marked.",
                    "error"
                );
                return;
            }

            const details = [
                result.message || "Attendance marked successfully.",
                result.subject
                    ? `${result.subject}${
                        result.subject_code
                            ? ` (${result.subject_code})`
                            : ""
                    }`
                    : ""
            ].filter(Boolean).join(" · ");

            attendanceSucceeded = true;
            tokenInput.value = "";

            setStatus("Attendance confirmed", details, "success");

        } catch (error) {
            console.error("Attendance marking error:", error);

            setStatus(
                "Attendance verification failed",
                locationErrorMessage(error),
                "error"
            );
        } finally {
            processing = false;
            updateButtons();
        }

        if (attendanceSucceeded && scanner) {
            await stopScanner();
        }
    }

    async function startScanner() {
        if (
            scanner ||
            scannerStarting ||
            scannerStopping ||
            processing
        ) {
            return;
        }

        if (!window.Html5Qrcode) {
            setStatus(
                "Scanner unavailable",
                "The QR-scanning library could not be loaded. You can enter a token manually.",
                "error"
            );
            return;
        }

        if (!window.isSecureContext) {
            setStatus(
                "Secure connection required",
                "Camera and location access generally require HTTPS or localhost.",
                "error"
            );
            return;
        }

        scannerStarting = true;
        updateButtons();

        setStatus(
            "Starting camera",
            "Please allow camera access when your browser asks.",
            "loading"
        );

        const newScanner = new window.Html5Qrcode("reader");
        scanner = newScanner;

        try {
            await newScanner.start(
                { facingMode: "environment" },
                {
                    fps: 10,
                    qrbox: { width: 250, height: 250 },
                    aspectRatio: 1
                },
                decodedText => {
                    if (
                        processing ||
                        scannerStarting ||
                        scannerStopping
                    ) {
                        return;
                    }

                    markAttendance(decodedText, false);
                },
                () => {
                    // Normal unsuccessful scan frames are ignored.
                }
            );

            setStatus(
                "Camera ready",
                "Point the camera at the active QR code displayed by your faculty.",
                "info"
            );

        } catch (error) {
            console.error("Unable to start QR scanner:", error);

            try {
                await newScanner.clear();
            } catch {
                // The scanner may not have initialized completely.
            }

            if (scanner === newScanner) {
                scanner = null;
            }

            setStatus(
                "Camera could not start",
                "Check camera permission, close other apps using the camera, or enter the token manually.",
                "error"
            );
        } finally {
            scannerStarting = false;
            updateButtons();
        }
    }

    startButton.addEventListener("click", startScanner);

    stopButton.addEventListener("click", async () => {
        await stopScanner();

        if (!processing) {
            setStatus(
                "Camera stopped",
                "Start the camera again or enter a token manually.",
                "info"
            );
        }
    });

    manualForm.addEventListener("submit", event => {
        event.preventDefault();
        markAttendance(tokenInput.value, true);
    });

    window.addEventListener("pagehide", () => {
        if (scanner) {
            scanner.stop().catch(() => {});
        }
    });

    updateButtons();
}


/* ============================================================
   4. STUDENT REGISTRATION PAGE
   Filters department -> semester -> division.
   ============================================================ */

function initializeStudentRegistration() {
    const departmentSelect = document.getElementById("department_id");
    const semesterSelect = document.getElementById("semester_id");
    const divisionSelect = document.getElementById("division_id");

    if (!departmentSelect || !semesterSelect || !divisionSelect) {
        return;
    }

    function filterSemesters() {
        const departmentId = departmentSelect.value;

        semesterSelect.value = "";
        divisionSelect.value = "";

        for (const option of semesterSelect.options) {
            if (!option.value) {
                continue;
            }

            const matches =
                departmentId !== "" &&
                option.dataset.department === departmentId;

            option.hidden = !matches;
        }

        semesterSelect.disabled = !departmentId;

        semesterSelect.options[0].textContent = departmentId
            ? "Select Semester"
            : "Select Department First";

        filterDivisions();
    }

    function filterDivisions() {
        const departmentId = departmentSelect.value;
        const semesterId = semesterSelect.value;

        for (const option of divisionSelect.options) {
            if (!option.value) {
                continue;
            }

            const matches =
                departmentId !== "" &&
                semesterId !== "" &&
                option.dataset.department === departmentId &&
                option.dataset.semester === semesterId;

            option.hidden = !matches;
        }

        divisionSelect.disabled = !departmentId || !semesterId;

        divisionSelect.options[0].textContent =
            !departmentId
                ? "Select Department First"
                : !semesterId
                    ? "Select Semester First"
                    : "Select Division";
    }

    departmentSelect.addEventListener("change", filterSemesters);

    semesterSelect.addEventListener("change", () => {
        divisionSelect.value = "";
        filterDivisions();
    });

    // Prevent accidental double submission of the registration form.
    const registrationForm = departmentSelect.closest("form");

    if (registrationForm) {
        registrationForm.addEventListener("submit", event => {
            if (!registrationForm.checkValidity()) {
                return;
            }

            const submitButton = registrationForm.querySelector(
                'button[type="submit"]'
            );

            if (submitButton?.dataset.submitting === "true") {
                event.preventDefault();
                return;
            }

            if (submitButton) {
                submitButton.dataset.submitting = "true";
                submitButton.disabled = true;
                submitButton.innerHTML = `
                    <span
                        class="spinner-border spinner-border-sm me-2"
                        role="status"
                    ></span>
                    Creating account...
                `;
            }
        });
    }

    filterSemesters();
}
