const state = {
  project: null,
  tools: [],
  activeGateId: "",
  externalFollowupTimer: null,
  externalAutomationPlanPath: "",
  bridgeStatus: null,
  providerAutosaveTimers: {},
  providerDraftHashes: {},
};

const el = {
  root: document.querySelector("#projectRoot"),
  question: document.querySelector("#questionInput"),
  deepQuestion: document.querySelector("#deepResearchQuestionInput"),
  deepClarifications: document.querySelector("#deepResearchClarifications"),
  deepSourcePolicy: document.querySelector("#deepResearchSourcePolicy"),
  deepProviderGrid: document.querySelector("#deepProviderGrid"),
  selectedProviderSummary: document.querySelector("#selectedProviderSummary"),
  selectCoreProviders: document.querySelector("#selectCoreProvidersBtn"),
  selectAllProviders: document.querySelector("#selectAllProvidersBtn"),
  clearProviders: document.querySelector("#clearProvidersBtn"),
  deepInitProject: document.querySelector("#deepInitProjectBtn"),
  deepPreparePlan: document.querySelector("#deepPreparePlanBtn"),
  deepCopyPrompt: document.querySelector("#deepCopyPromptBtn"),
  deepOpenLogin: document.querySelector("#deepOpenLoginBtn"),
  deepPreflight: document.querySelector("#deepPreflightBtn"),
  deepRunAutomation: document.querySelector("#deepRunAutomationBtn"),
  deepExportMarkdown: document.querySelector("#deepExportMarkdownBtn"),
  deepManualReportProvider: document.querySelector("#deepManualReportProvider"),
  deepManualReportUrl: document.querySelector("#deepManualReportUrl"),
  deepManualReportText: document.querySelector("#deepManualReportText"),
  deepImportManualReport: document.querySelector("#deepImportManualReportBtn"),
  providerPasteGrid: document.querySelector("#providerPasteGrid"),
  providerPasteProgress: document.querySelector("#providerPasteProgress"),
  deepMergeWhenComplete: document.querySelector("#deepMergeWhenCompleteBtn"),
  deepMergeResult: document.querySelector("#deepMergeResult"),
  deepLaunchStatus: document.querySelector("#deepLaunchStatus"),
  loadProject: document.querySelector("#loadProjectBtn"),
  initProject: document.querySelector("#initProjectBtn"),
  projectDot: document.querySelector("#projectDot"),
  projectStatus: document.querySelector("#projectStatus"),
  projectTitle: document.querySelector("#projectTitle"),
  projectMeta: document.querySelector("#projectMeta"),
  sourceCount: document.querySelector("#sourceCount"),
  claimCount: document.querySelector("#claimCount"),
  evidenceCount: document.querySelector("#evidenceCount"),
  reviewCount: document.querySelector("#reviewCount"),
  dashboardStage: document.querySelector("#dashboardStage"),
  stageDetailSummary: document.querySelector("#stageDetailSummary"),
  claimCoverage: document.querySelector("#claimCoverage"),
  verifiedCoverage: document.querySelector("#verifiedCoverage"),
  gateCoverage: document.querySelector("#gateCoverage"),
  dashboardReviewQueue: document.querySelector("#dashboardReviewQueue"),
  sourceQualityRows: document.querySelector("#sourceQualityRows"),
  dashboardGapRows: document.querySelector("#dashboardGapRows"),
  dashboardActionRows: document.querySelector("#dashboardActionRows"),
  localToolHealthRows: document.querySelector("#localToolHealthRows"),
  overviewClaimRows: document.querySelector("#overviewClaimRows"),
  overviewArtifactRows: document.querySelector("#overviewArtifactRows"),
  completenessAudit: document.querySelector("#completenessAuditBtn"),
  completenessAuditRows: document.querySelector("#completenessAuditRows"),
  plan: document.querySelector("#planBtn"),
  planAddClaims: document.querySelector("#planAddClaimsBtn"),
  searchQuery: document.querySelector("#searchQuery"),
  searchMode: document.querySelector("#searchMode"),
  searchMaxResults: document.querySelector("#searchMaxResults"),
  aiResearchBaseUrl: document.querySelector("#aiResearchBaseUrl"),
  aiResearchStatus: document.querySelector("#aiResearchStatusBtn"),
  searchPlan: document.querySelector("#searchPlanBtn"),
  searchPreview: document.querySelector("#searchPreviewBtn"),
  searchImport: document.querySelector("#searchImportBtn"),
  searchRuns: document.querySelector("#searchRunsBtn"),
  aiResearchResultPath: document.querySelector("#aiResearchResultPath"),
  importAiResearchResult: document.querySelector("#importAiResearchResultBtn"),
  aiResearchBridgeSummary: document.querySelector("#aiResearchBridgeSummary"),
  aiResearchResultRows: document.querySelector("#aiResearchResultRows"),
  vaneBaseUrl: document.querySelector("#vaneBaseUrl"),
  vaneSources: document.querySelector("#vaneSources"),
  vaneOptimization: document.querySelector("#vaneOptimization"),
  vaneChatModelKey: document.querySelector("#vaneChatModelKey"),
  vaneEmbeddingModelKey: document.querySelector("#vaneEmbeddingModelKey"),
  vaneStatus: document.querySelector("#vaneStatusBtn"),
  vanePlan: document.querySelector("#vanePlanBtn"),
  vanePreview: document.querySelector("#vanePreviewBtn"),
  vaneImport: document.querySelector("#vaneImportBtn"),
  vaneBridgeSummary: document.querySelector("#vaneBridgeSummary"),
  vaneResultRows: document.querySelector("#vaneResultRows"),
  externalProviders: document.querySelector("#externalProviders"),
  externalSourcePolicy: document.querySelector("#externalSourcePolicy"),
  externalOutputLanguage: document.querySelector("#externalOutputLanguage"),
  externalProfileConfigPath: document.querySelector("#externalProfileConfigPath"),
  externalFollowupWaitSeconds: document.querySelector("#externalFollowupWaitSeconds"),
  externalMaxWaitSeconds: document.querySelector("#externalMaxWaitSeconds"),
  externalClarifications: document.querySelector("#externalClarifications"),
  externalPlan: document.querySelector("#externalPlanBtn"),
  externalAutomationPlan: document.querySelector("#externalAutomationPlanBtn"),
  externalAutomationCheck: document.querySelector("#externalAutomationCheckBtn"),
  externalAutomationLiveCheck: document.querySelector("#externalAutomationLiveCheckBtn"),
  externalLoginPrepPlan: document.querySelector("#externalLoginPrepPlanBtn"),
  externalLoginPrepLive: document.querySelector("#externalLoginPrepLiveBtn"),
  externalAutomationRun: document.querySelector("#externalAutomationRunBtn"),
  externalProfileTemplate: document.querySelector("#externalProfileTemplateBtn"),
  externalListReports: document.querySelector("#externalListReportsBtn"),
  externalExport: document.querySelector("#externalExportBtn"),
  externalBridgeSummary: document.querySelector("#externalBridgeSummary"),
  externalPromptOutput: document.querySelector("#externalPromptOutput"),
  externalAutomationOutput: document.querySelector("#externalAutomationOutput"),
  externalFollowupCountdown: document.querySelector("#externalFollowupCountdown"),
  externalFollowupQuestion: document.querySelector("#externalFollowupQuestion"),
  externalManualAnswer: document.querySelector("#externalManualAnswer"),
  externalStartCountdown: document.querySelector("#externalStartCountdownBtn"),
  externalManualAnswerBtn: document.querySelector("#externalManualAnswerBtn"),
  externalAutoAnswer: document.querySelector("#externalAutoAnswerBtn"),
  externalFollowupAnswerOutput: document.querySelector("#externalFollowupAnswerOutput"),
  externalReportProvider: document.querySelector("#externalReportProvider"),
  externalReportUrl: document.querySelector("#externalReportUrl"),
  externalReportNotes: document.querySelector("#externalReportNotes"),
  externalReportText: document.querySelector("#externalReportText"),
  externalImportReport: document.querySelector("#externalImportReportBtn"),
  externalReportRows: document.querySelector("#externalReportRows"),
  routeTask: document.querySelector("#routeTaskBtn"),
  gateAudit: document.querySelector("#gateAuditBtn"),
  perspectiveReview: document.querySelector("#perspectiveReviewBtn"),
  personaReview: document.querySelector("#personaReviewBtn"),
  workflowEngine: document.querySelector("#workflowEngineBtn"),
  materialHint: document.querySelector("#materialHint"),
  targetStage: document.querySelector("#targetStage"),
  gateSummary: document.querySelector("#gateSummary"),
  gateRows: document.querySelector("#gateRows"),
  gateDetailRows: document.querySelector("#gateDetailRows"),
  nextStepRows: document.querySelector("#nextStepRows"),
  workflowArtifactRows: document.querySelector("#workflowArtifactRows"),
  reviewQueueRows: document.querySelector("#reviewQueueRows"),
  sourceInboxKind: document.querySelector("#sourceInboxKind"),
  sourceInboxTitle: document.querySelector("#sourceInboxTitle"),
  sourceInboxLocation: document.querySelector("#sourceInboxLocation"),
  sourceInboxTool: document.querySelector("#sourceInboxTool"),
  sourceInboxQualityHint: document.querySelector("#sourceInboxQualityHint"),
  addSourceInboxItem: document.querySelector("#addSourceInboxItemBtn"),
  refreshSourceInbox: document.querySelector("#refreshSourceInboxBtn"),
  sourceInboxRows: document.querySelector("#sourceInboxRows"),
  sourceRows: document.querySelector("#sourceRows"),
  sourceTitle: document.querySelector("#sourceTitle"),
  sourceType: document.querySelector("#sourceType"),
  sourceUrl: document.querySelector("#sourceUrl"),
  sourcePath: document.querySelector("#sourcePath"),
  sourceQuality: document.querySelector("#sourceQuality"),
  sourceNotes: document.querySelector("#sourceNotes"),
  addSource: document.querySelector("#addSourceBtn"),
  fetchSourceSelect: document.querySelector("#fetchSourceSelect"),
  fetchClaimSelect: document.querySelector("#fetchClaimSelect"),
  fetchDirectUrl: document.querySelector("#fetchDirectUrl"),
  fetchUseBrowser: document.querySelector("#fetchUseBrowser"),
  fetchIncludeRaw: document.querySelector("#fetchIncludeRaw"),
  fetchPlan: document.querySelector("#fetchPlanBtn"),
  fetchSource: document.querySelector("#fetchSourceBtn"),
  fetchEvidence: document.querySelector("#fetchEvidenceBtn"),
  webFetchBridgeSummary: document.querySelector("#webFetchBridgeSummary"),
  webFetchResultRows: document.querySelector("#webFetchResultRows"),
  claimText: document.querySelector("#claimText"),
  claimNotes: document.querySelector("#claimNotes"),
  addClaim: document.querySelector("#addClaimBtn"),
  claimList: document.querySelector("#claimList"),
  evidenceClaim: document.querySelector("#evidenceClaim"),
  evidenceSource: document.querySelector("#evidenceSource"),
  evidenceRelation: document.querySelector("#evidenceRelation"),
  evidenceConfidence: document.querySelector("#evidenceConfidence"),
  evidenceQuote: document.querySelector("#evidenceQuote"),
  addEvidence: document.querySelector("#addEvidenceBtn"),
  evidenceList: document.querySelector("#evidenceList"),
  toolCards: document.querySelector("#toolCards"),
  toolHealthList: document.querySelector("#toolHealthList"),
  refreshTools: document.querySelector("#refreshToolsBtn"),
  videoHealth: document.querySelector("#videoHealthBtn"),
  videoMediaPath: document.querySelector("#videoMediaPath"),
  videoWorkspace: document.querySelector("#videoWorkspace"),
  videoTitle: document.querySelector("#videoTitle"),
  videoMaxFrames: document.querySelector("#videoMaxFrames"),
  videoPlan: document.querySelector("#videoPlanBtn"),
  videoArtifactCheck: document.querySelector("#videoArtifactCheckBtn"),
  videoBundleDir: document.querySelector("#videoBundleDir"),
  videoImportClaimSelect: document.querySelector("#videoImportClaimSelect"),
  videoImport: document.querySelector("#videoImportBtn"),
  videoBridgeSummary: document.querySelector("#videoBridgeSummary"),
  videoBridgeResultRows: document.querySelector("#videoBridgeResultRows"),
  videoArgs: document.querySelector("#videoArgs"),
  runVideoTool: document.querySelector("#runVideoToolBtn"),
  localToolId: document.querySelector("#localToolId"),
  localToolAction: document.querySelector("#localToolAction"),
  localToolArgs: document.querySelector("#localToolArgs"),
  localToolDryRun: document.querySelector("#localToolDryRunBtn"),
  localToolActionRows: document.querySelector("#localToolActionRows"),
  researchGapQuery: document.querySelector("#researchGapQuery"),
  researchGapMaxQueries: document.querySelector("#researchGapMaxQueries"),
  researchGapAnalyze: document.querySelector("#researchGapAnalyzeBtn"),
  researchLoopRounds: document.querySelector("#researchLoopRounds"),
  researchLoopMaxResults: document.querySelector("#researchLoopMaxResults"),
  researchLoopId: document.querySelector("#researchLoopId"),
  researchLoopRun: document.querySelector("#researchLoopRunBtn"),
  researchLoopList: document.querySelector("#researchLoopListBtn"),
  researchLoopRead: document.querySelector("#researchLoopReadBtn"),
  researchLoopExport: document.querySelector("#researchLoopExportBtn"),
  researchLoopSummary: document.querySelector("#researchLoopSummary"),
  researchLoopResultRows: document.querySelector("#researchLoopResultRows"),
  bridgeActionName: document.querySelector("#bridgeActionName"),
  bridgeActionArgs: document.querySelector("#bridgeActionArgs"),
  bridgeActionPlan: document.querySelector("#bridgeActionPlanBtn"),
  bridgeActionRun: document.querySelector("#bridgeActionRunBtn"),
  enqueueBridgeActions: document.querySelector("#enqueueBridgeActionsBtn"),
  bridgeActionResultRows: document.querySelector("#bridgeActionResultRows"),
  refreshToolBridgeStatus: document.querySelector("#refreshToolBridgeStatusBtn"),
  bridgeRunId: document.querySelector("#bridgeRunId"),
  readBridgeRun: document.querySelector("#readBridgeRunBtn"),
  retryBridgeRun: document.querySelector("#retryBridgeRunBtn"),
  backendModeBanner: document.querySelector("#backendModeBanner"),
  toolBridgeStatusRows: document.querySelector("#toolBridgeStatusRows"),
  syncSafety: document.querySelector("#syncSafetyBtn"),
  syncSafetyRows: document.querySelector("#syncSafetyRows"),
  generateGraphCandidates: document.querySelector("#generateGraphCandidatesBtn"),
  refreshGraphCandidates: document.querySelector("#refreshGraphCandidatesBtn"),
  exportReviewedGraph: document.querySelector("#exportReviewedGraphBtn"),
  graphStatusFilter: document.querySelector("#graphStatusFilter"),
  graphEdgeTypeFilter: document.querySelector("#graphEdgeTypeFilter"),
  graphCandidateRows: document.querySelector("#graphCandidateRows"),
  overview: document.querySelector("#overviewBtn"),
  draft: document.querySelector("#draftBtn"),
  exportFinalAnswer: document.querySelector("#exportFinalAnswerBtn"),
  exportResearchPack: document.querySelector("#exportResearchPackBtn"),
  exportObsidianPack: document.querySelector("#exportObsidianPackBtn"),
  logseqHandoff: document.querySelector("#logseqHandoffBtn"),
  obsidianVault: document.querySelector("#obsidianVault"),
  obsidianFolder: document.querySelector("#obsidianFolder"),
  agentRunbook: document.querySelector("#agentRunbookBtn"),
  agentManifest: document.querySelector("#agentManifestBtn"),
  cockpitReadiness: document.querySelector("#cockpitReadinessBtn"),
  enqueueRunbookTasks: document.querySelector("#enqueueRunbookTasksBtn"),
  refreshWorkQueue: document.querySelector("#refreshWorkQueueBtn"),
  workQueuePanel: document.querySelector("#workQueuePanel"),
  output: document.querySelector("#reportOutput"),
  notice: document.querySelector("#notice"),
};

el.root.value = el.root.value || ".research-question";
el.deepQuestion.value = el.question.value;
el.deepClarifications.value = el.externalClarifications?.value || "";
el.deepSourcePolicy.value = el.externalSourcePolicy?.value || el.deepSourcePolicy.value;

function selectedDeepProviders() {
  return Array.from(document.querySelectorAll(".deep-provider-checkbox:checked")).map((input) => input.value);
}

function syncDeepProvidersToExternalField() {
  const selected = selectedDeepProviders();
  el.externalProviders.value = selected.join(", ");
  el.selectedProviderSummary.textContent = selected.length ? `${selected.length} auto-ready` : "manual only";
  el.selectedProviderSummary.className = `pill ${selected.length ? "ok" : "bad"}`;
  el.deepLaunchStatus.innerHTML = `
    <span class="pill ${selected.length ? "ok" : "bad"}">${selected.length ? "ready" : "empty"}</span>
    <strong>${selected.length ? `可选自动化：${safe(selected.join(" / "))}` : "手动粘贴通道仍可继续使用"}</strong>
  `;
  return selected;
}

function syncDeepLaunchInputs() {
  el.question.value = el.deepQuestion.value;
  el.externalClarifications.value = el.deepClarifications.value;
  el.externalSourcePolicy.value = el.deepSourcePolicy.value;
  syncDeepProvidersToExternalField();
}

function setProviderSelection(mode) {
  const core = new Set(["豆包深入研究", "通义千问研究"]);
  document.querySelectorAll(".deep-provider-checkbox").forEach((input) => {
    input.checked = mode === "all" ? true : mode === "core" ? core.has(input.value) : false;
  });
  syncDeepProvidersToExternalField();
}

async function initProjectFromDeepLaunch() {
  syncDeepLaunchInputs();
  if (!el.question.value.trim()) {
    throw new Error("请先填写研究问题。");
  }
  const data = await postJSON("/api/project/init", { question: el.question.value });
  renderProject(data.state);
  if (data.state?.project?.question) {
    el.deepQuestion.value = data.state.project.question;
  }
  clearExternalResearcherInboxForNewQuestion();
  setNotice("研究问题已保存。", "ok");
}

async function deepPreparePlan() {
  syncDeepLaunchInputs();
  if (!selectedDeepProviders().length) {
    setProviderSelection("core");
  }
  if (!el.question.value.trim()) {
    throw new Error("请先填写研究问题。");
  }
  await planExternalResearcherAutomation();
  el.deepLaunchStatus.innerHTML = `<span class="pill ok">prompt</span><strong>统一提示词已生成，可以复制到任意网页端。</strong>`;
}

async function copyDeepResearchPrompt() {
  syncDeepLaunchInputs();
  if (!el.externalPromptOutput.value.trim()) {
    await deepPreparePlan();
  }
  const prompt = el.externalPromptOutput.value.trim();
  if (!prompt) {
    throw new Error("还没有可复制的深研提示词。");
  }
  try {
    await navigator.clipboard.writeText(prompt);
    setNotice("统一深研提示词已复制。", "ok");
    el.deepLaunchStatus.innerHTML = `<span class="pill ok">copied</span><strong>现在可以去任意网页端粘贴同一份提示词。</strong>`;
  } catch (error) {
    el.output.textContent = prompt;
    setNotice("浏览器不允许直接写剪贴板，提示词已放到右侧输出区。", "warn");
  }
}

async function importManualDeepReport() {
  syncDeepLaunchInputs();
  const reportText = el.deepManualReportText.value.trim();
  if (!reportText) {
    throw new Error("请先粘贴一份外部深度研究报告。");
  }
  el.externalReportProvider.value = el.deepManualReportProvider.value.trim() || "手动粘贴外部深度研究";
  el.externalReportUrl.value = el.deepManualReportUrl.value.trim();
  el.externalReportNotes.value = "从启动台手动粘贴保存；仍作为候选上下文，待来源复核。";
  el.externalReportText.value = reportText;
  await importExternalReport();
  el.deepManualReportText.value = "";
  el.deepLaunchStatus.innerHTML = `<span class="pill ok">saved</span><strong>粘贴报告已保存，可以继续粘贴下一家或导出汇总 MD。</strong>`;
}

function providerPasteCards() {
  return Array.from(document.querySelectorAll("[data-provider-card]"));
}

function currentProjectDraftScope() {
  const rootScope = String(el.root.value || "").trim().replace(/\\/g, "/").toLowerCase();
  const projectId = String(state.project?.project?.id || "").trim();
  const question = String(state.project?.project?.question || el.question.value || el.deepQuestion.value || "").trim();
  return `${rootScope}:${projectId || "uninitialized"}:${providerQuestionFingerprint(question)}`;
}

function providerQuestionFingerprint(question) {
  let hash = 0;
  const text = String(question || "");
  for (let index = 0; index < text.length; index += 1) {
    hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function providerDraftKey(provider) {
  return `question-research-poc:provider-draft:${currentProjectDraftScope()}:${provider}`;
}

function providerDraftHash(text) {
  return `${text.length}:${text.slice(0, 80)}:${text.slice(-80)}`;
}

function saveProviderDraftLocally(provider, text) {
  try {
    window.localStorage.setItem(providerDraftKey(provider), text);
  } catch (error) {
    // Local draft persistence is best-effort; backend autosave still runs.
  }
}

function restoreProviderDrafts() {
  document.querySelectorAll("[data-provider-report]").forEach((textarea) => {
    const provider = textarea.dataset.providerReport || "";
    if (!provider || textarea.value.trim()) return;
    try {
      const draft = window.localStorage.getItem(providerDraftKey(provider)) || "";
      if (draft) {
        textarea.value = draft;
        markProviderCardArchived(provider, "本地草稿");
      }
    } catch (error) {
      // Ignore localStorage failures.
    }
  });
}

function resetProviderPasteInbox() {
  Object.values(state.providerAutosaveTimers).forEach((timer) => window.clearTimeout(timer));
  state.providerAutosaveTimers = {};
  state.providerDraftHashes = {};
  providerPasteCards().forEach((card) => {
    card.classList.remove("archived");
    const status = card.querySelector("[data-provider-status]");
    if (status) status.textContent = "待粘贴";
  });
  document.querySelectorAll("[data-provider-report]").forEach((textarea) => {
    textarea.value = "";
  });
  el.deepMergeResult.innerHTML = `<span class="pill">idle</span><strong>整合后会在这里显示 Markdown 文件路径。</strong>`;
  updateProviderPasteProgress();
}

function clearExternalResearcherInboxForNewQuestion() {
  resetProviderPasteInbox();
  if (el.externalReportRows) {
    el.externalReportRows.innerHTML = `<div class="empty-state">当前新问题还没有保存外部深度研究报告。</div>`;
  }
  el.deepMergeResult.innerHTML = `<span class="pill">idle</span><strong>新研究问题已创建；旧问题回答不会自动带入。</strong>`;
  el.deepLaunchStatus.innerHTML = `<span class="pill ok">new</span><strong>新问题已创建，AI 回答收件箱已清空。</strong>`;
}

function renderProviderPasteReports(payload) {
  resetProviderPasteInbox();
  const latestByProvider = new Map();
  (payload?.reports || []).forEach((report) => {
    const provider = report.provider || "";
    if (!provider) return;
    const existing = latestByProvider.get(provider);
    if (!existing || String(report.created_at || "") >= String(existing.created_at || "")) {
      latestByProvider.set(provider, report);
    }
  });
  latestByProvider.forEach((report, provider) => {
    const textarea = document.querySelector(`[data-provider-report="${CSS.escape(provider)}"]`);
    if (!textarea) return;
    textarea.value = report.report_text || "";
    if (textarea.value.trim()) {
      state.providerDraftHashes[provider] = providerDraftHash(textarea.value.trim());
      markProviderCardArchived(provider, report.draft ? "已保存草稿" : "已存档");
    }
  });
  restoreProviderDrafts();
  updateProviderPasteProgress();
}

function updateProviderPasteProgress() {
  const cards = providerPasteCards();
  const archived = cards.filter((card) => card.classList.contains("archived")).length;
  const total = cards.length;
  el.providerPasteProgress.textContent = `${archived} / ${total} 已存档`;
  el.providerPasteProgress.className = `pill ${archived ? "ok" : ""}`;
  el.deepMergeWhenComplete.disabled = archived === 0;
  return { archived, total };
}

function markProviderCardArchived(provider, statusText = "已存档") {
  const card = document.querySelector(`[data-provider-card="${CSS.escape(provider)}"]`);
  if (!card) return updateProviderPasteProgress();
  card.classList.add("archived");
  const status = card.querySelector("[data-provider-status]");
  if (status) status.textContent = statusText;
  return updateProviderPasteProgress();
}

async function autosaveProviderDraft(provider, url, text) {
  const cleanText = String(text || "").trim();
  if (!provider || !cleanText) return null;
  const hash = providerDraftHash(cleanText);
  if (state.providerDraftHashes[provider] === hash) {
    return null;
  }
  const data = await postJSON("/api/external-researcher-report", {
    provider,
    report_url: url || "",
    notes: "AI 回答收件箱自动保存草稿；仍作为候选上下文，待来源复核。",
    prompt_text: el.externalPromptOutput.value,
    report_text: cleanText,
    import_as_source: false,
  });
  state.providerDraftHashes[provider] = hash;
  if (data.state) renderProject(data.state);
  renderExternalReports(data.reports);
  markProviderCardArchived(provider, "已自动保存");
  el.deepLaunchStatus.innerHTML = `<span class="pill ok">autosaved</span><strong>${safe(provider)} 草稿已自动保存。</strong>`;
  el.deepMergeResult.innerHTML = `
    <span class="pill ok">saved</span>
    <div>
      <strong>${safe(provider)} 已自动保存</strong>
      <small>Markdown: <code>${safe(data.result?.markdown_path || "")}</code></small>
      <small>JSON: <code>${safe(data.result?.json_path || "")}</code></small>
    </div>
  `;
  return data;
}

function scheduleProviderDraftAutosave(textarea) {
  const provider = textarea.dataset.providerReport || "";
  const card = document.querySelector(`[data-provider-card="${CSS.escape(provider)}"]`);
  const button = card?.querySelector("[data-paste-provider]");
  const url = button?.dataset.pasteUrl || "";
  const text = textarea.value;
  saveProviderDraftLocally(provider, text);
  if (!text.trim()) return;
  const status = card?.querySelector("[data-provider-status]");
  if (status) status.textContent = "本地草稿";
  window.clearTimeout(state.providerAutosaveTimers[provider]);
  state.providerAutosaveTimers[provider] = window.setTimeout(() => {
    autosaveProviderDraft(provider, url, text).catch((error) => {
      el.deepMergeResult.innerHTML = `<span class="pill bad">failed</span><strong>${safe(provider)} 自动保存失败：${safe(error.message)}</strong>`;
      setNotice(`${provider} 自动保存失败：${error.message}`, "error");
    });
  }, 900);
}

async function flushProviderDraftAutosaves() {
  const tasks = [];
  document.querySelectorAll("[data-provider-report]").forEach((textarea) => {
    const provider = textarea.dataset.providerReport || "";
    window.clearTimeout(state.providerAutosaveTimers[provider]);
    const card = document.querySelector(`[data-provider-card="${CSS.escape(provider)}"]`);
    const button = card?.querySelector("[data-paste-provider]");
    tasks.push(autosaveProviderDraft(provider, button?.dataset.pasteUrl || "", textarea.value));
  });
  await Promise.all(tasks);
}

async function readClipboardTextForProvider() {
  if (!navigator.clipboard || !navigator.clipboard.readText) {
    throw new Error("当前浏览器不允许读取剪贴板，请用下方备用粘贴框。");
  }
  const text = (await navigator.clipboard.readText()).trim();
  if (!text) {
    throw new Error("剪贴板里没有可保存的回答文本。");
  }
  return text;
}

async function archiveProviderClipboardAnswer(provider, url, text) {
  el.externalReportProvider.value = provider;
  el.externalReportUrl.value = url || "";
  el.externalReportNotes.value = "从 AI 回答收件箱图标读取剪贴板并自动存档；仍作为候选上下文，待来源复核。";
  el.externalReportText.value = text;
  await importExternalReport();
  markProviderCardArchived(provider);
  const progress = updateProviderPasteProgress();
  el.deepLaunchStatus.innerHTML = `
    <span class="pill ok">saved</span>
    <strong>${safe(provider)} 已存档；当前 ${progress.archived} / ${progress.total}。</strong>
  `;
}

async function pasteProviderAnswerFromClipboard(button) {
  syncDeepLaunchInputs();
  const provider = button.dataset.pasteProvider || "";
  const url = button.dataset.pasteUrl || "";
  const text = await readClipboardTextForProvider();
  const textarea = document.querySelector(`[data-provider-report="${CSS.escape(provider)}"]`);
  if (textarea) {
    textarea.value = text;
    saveProviderDraftLocally(provider, text);
  }
  button.disabled = true;
  try {
    await archiveProviderClipboardAnswer(provider, url, text);
  } finally {
    button.disabled = false;
  }
}

async function mergeArchivedProviderReports() {
  await flushProviderDraftAutosaves();
  const progress = updateProviderPasteProgress();
  if (!progress.archived) {
    throw new Error("至少先存档一份 AI 回答。");
  }
  const previousLabel = el.deepMergeWhenComplete.textContent;
  el.deepMergeWhenComplete.disabled = true;
  el.deepMergeWhenComplete.textContent = "正在整合...";
  el.deepMergeResult.innerHTML = `<span class="pill warn">running</span><strong>正在生成汇总 Markdown。</strong>`;
  try {
    const data = await exportExternalBundle();
    renderDeepMergeResult(data.result, progress.archived);
    el.deepLaunchStatus.innerHTML = `<span class="pill ok">merged</span><strong>${progress.archived} 份已存档回答已汇总成 Markdown。</strong>`;
  } catch (error) {
    el.deepMergeResult.innerHTML = `<span class="pill bad">failed</span><strong>${safe(error.message || "整合失败")}</strong>`;
    throw error;
  } finally {
    el.deepMergeWhenComplete.textContent = previousLabel;
    updateProviderPasteProgress();
  }
}

async function deepOpenLoginWindows() {
  syncDeepLaunchInputs();
  if (!selectedDeepProviders().length) {
    throw new Error("请至少勾选一个 AI。");
  }
  if (!state.externalAutomationPlanPath) {
    await planExternalResearcherAutomation();
  }
  el.deepLaunchStatus.innerHTML = `<span class="pill warn">diagnose</span><strong>正在打开已勾选平台的登录/诊断窗口。</strong>`;
  await prepareExternalResearcherLoginProfiles(true);
}

async function deepPreflightWindows() {
  syncDeepLaunchInputs();
  if (!state.externalAutomationPlanPath) {
    await planExternalResearcherAutomation();
  }
  el.deepLaunchStatus.innerHTML = `<span class="pill warn">preflight</span><strong>正在检查已勾选平台是否适合自动化。</strong>`;
  await checkExternalResearcherAutomation(true);
}

async function deepRunLiveAutomation() {
  syncDeepLaunchInputs();
  if (!selectedDeepProviders().length) {
    throw new Error("请至少勾选一个 AI。");
  }
  if (!el.question.value.trim()) {
    throw new Error("请先填写研究问题。");
  }
  if (!state.externalAutomationPlanPath) {
    await planExternalResearcherAutomation();
  }
  el.deepLaunchStatus.innerHTML = `<span class="pill warn">optional</span><strong>只对已勾选且可用的平台尝试自动提交；失败就改走粘贴通道。</strong>`;
  await runExternalResearcherAutomation();
}

function setNotice(message, kind = "") {
  el.notice.textContent = message;
  el.notice.className = `notice ${kind}`.trim();
}

async function getJSON(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

async function getJSONLoose(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

async function postJSON(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ root: el.root.value, ...payload }),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function safe(value) {
  return String(value || "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char]));
}

function renderProject(data) {
  state.project = data;
  const sources = data.sources || [];
  const claims = data.claims || [];
  const evidence = data.evidence || [];
  const reviews = data.reviews || [];
  const loaded = Boolean(data.ok && data.project);
  el.projectDot.className = `dot ${loaded ? "ok" : "warn"}`;
  el.projectStatus.textContent = loaded ? "Project loaded" : "Project not initialized";
  el.projectTitle.textContent = loaded ? data.project.question : "问题主导研究总控台";
  el.projectMeta.textContent = loaded ? `${data.root} · ${data.project.status}` : data.root;
  if (loaded) {
    el.question.value = data.project.question;
    if (!el.deepQuestion.value.trim()) {
      el.deepQuestion.value = data.project.question;
    }
  }
  el.sourceCount.textContent = sources.length;
  el.claimCount.textContent = claims.length;
  el.evidenceCount.textContent = evidence.length;
  el.reviewCount.textContent = reviews.length;
  renderDashboard(data.dashboard || {}, data.overview || {});
  el.sourceRows.innerHTML = sources.map((source) => `
    <tr>
      <td><span class="pill ${source.quality === "good" ? "ok" : source.quality === "poor" ? "bad" : ""}">${safe(source.quality || "unknown")}</span></td>
      <td>${safe(source.source_type)}</td>
      <td>${safe(source.title)}</td>
      <td>${safe(source.url || source.path)}</td>
      <td class="row-actions">
        <button class="mini-btn" type="button" data-source-review="${safe(source.id)}" data-quality="good">好</button>
        <button class="mini-btn" type="button" data-source-review="${safe(source.id)}" data-quality="poor">差</button>
      </td>
    </tr>
  `).join("");
  el.claimList.innerHTML = claims.map((claim) => `<div class="list-item"><strong>${safe(claim.text)}</strong><span>${safe(claim.id)}</span></div>`).join("");
  el.evidenceClaim.innerHTML = claims.map((claim) => `<option value="${safe(claim.id)}">${safe(claim.text)}</option>`).join("");
  el.evidenceSource.innerHTML = sources.map((source) => `<option value="${safe(source.id)}">${safe(source.title)}</option>`).join("");
  el.fetchSourceSelect.innerHTML = sources.map((source) => `<option value="${safe(source.id)}">${safe(source.title)}</option>`).join("");
  el.fetchClaimSelect.innerHTML = [`<option value="">不生成证据</option>`].concat(claims.map((claim) => `<option value="${safe(claim.id)}">${safe(claim.text)}</option>`)).join("");
  el.videoImportClaimSelect.innerHTML = [`<option value="">只导入来源</option>`].concat(claims.map((claim) => `<option value="${safe(claim.id)}">${safe(claim.text)}</option>`)).join("");
  el.evidenceList.innerHTML = evidence.map((item) => `
    <div class="list-item">
      <strong>${safe(item.quote_or_note)}</strong>
      <span>${safe(item.relation)} · ${safe(item.status)} · ${safe(item.confidence)}</span>
      <div class="row-actions">
        <button class="mini-btn" type="button" data-evidence-review="${safe(item.id)}" data-status="verified">通过</button>
        <button class="mini-btn" type="button" data-evidence-review="${safe(item.id)}" data-status="rejected">拒绝</button>
      </div>
    </div>
  `).join("");
  renderGateWorkbench(data.workflow || {});
  renderReviewQueue(data.review_queue || []);
}

function renderDashboard(dashboard, overview = {}) {
  const metrics = dashboard.metrics || {};
  const stage = dashboard.stage_detail || {};
  const quality = dashboard.source_quality || {};
  const gaps = dashboard.gaps || [];
  const actions = dashboard.next_actions || [];
  const localTools = dashboard.local_tools?.tools || [];
  el.dashboardStage.textContent = stage.stage_label || dashboard.stage || "unknown";
  el.stageDetailSummary.innerHTML = stage.stage_id ? `
    <div>
      <strong>${safe(stage.blocking_gate || "next")}</strong>
      <span>${safe(stage.next_human_action || "")}</span>
      <small>Agent：${safe(stage.next_agent_action || "")}</small>
    </div>
  ` : `<div class="empty-state">阶段详情会在项目加载后显示。</div>`;
  el.claimCoverage.textContent = `${safe(metrics.claim_coverage_percent || 0)}%`;
  el.verifiedCoverage.textContent = `${safe(metrics.verified_claim_coverage_percent || 0)}%`;
  el.gateCoverage.textContent = `${safe(metrics.passed_gates || 0)} / ${safe(metrics.failed_gates || 0)}`;
  el.dashboardReviewQueue.textContent = safe(metrics.review_queue || 0);
  el.sourceQualityRows.innerHTML = ["good", "mixed", "poor", "unknown"].map((key) => `
    <div class="mini-stat-row"><span>${safe(key)}</span><strong>${safe(quality[key] || 0)}</strong></div>
  `).join("");
  el.dashboardGapRows.innerHTML = gaps.length ? gaps.map((gap) => `<div class="mini-list-row">${safe(gap)}</div>`).join("") : `<div class="empty-state">当前没有明显缺口。</div>`;
  el.dashboardActionRows.innerHTML = actions.length ? actions.map((action) => `<div class="mini-list-row">${safe(action)}</div>`).join("") : `<div class="empty-state">当前没有下一步建议。</div>`;
  el.localToolHealthRows.innerHTML = localTools.length ? localTools.map((tool) => `
    <div class="local-tool-row ${tool.available ? "ok" : "missing"}">
      <span class="pill ${tool.available ? "ok" : "bad"}">${tool.available ? "available" : "missing"}</span>
      <div>
        <strong>${safe(tool.name)}</strong>
        <small>${safe(tool.interface || "unknown interface")} · ${safe(tool.status)}</small>
        <small>${safe(tool.recommended_next_action)}</small>
      </div>
    </div>
  `).join("") : `<div class="empty-state">还没有本地工具健康数据。</div>`;
  renderProjectOverview(overview);
}

function renderProjectOverview(overview) {
  const claimRows = overview.claim_evidence || [];
  const artifacts = overview.important_artifacts || [];
  el.overviewClaimRows.innerHTML = claimRows.length ? claimRows.slice(0, 8).map((row) => `
    <div class="overview-row ${row.coverage_status}">
      <span class="pill">${safe(row.coverage_status)}</span>
      <div>
        <strong>${safe(row.claim)}</strong>
        <small>evidence ${safe(row.evidence_count)} · verified ${safe(row.verified_count)} · candidate ${safe(row.candidate_count)} · context ${safe(row.contradicts_or_context_count)}</small>
        <small>${safe((row.sources || []).join("；"))}</small>
      </div>
    </div>
  `).join("") : `<div class="empty-state">还没有主张-证据关系。</div>`;
  el.overviewArtifactRows.innerHTML = artifacts.length ? artifacts.map((artifact) => `
    <div class="overview-row ${artifact.complete ? "complete" : "missing"}">
      <span class="pill ${artifact.complete ? "ok" : "bad"}">${artifact.complete ? "完整" : "缺失"}</span>
      <div>
        <strong>${safe(artifact.title || artifact.id)}</strong>
        <small>${safe(artifact.markdown_path || artifact.json_path)}</small>
      </div>
    </div>
  `).join("") : `<div class="empty-state">还没有重要产物入口。</div>`;
}

function renderGateWorkbench(workflow) {
  const route = workflow.route || {};
  const audit = workflow.gate_audit || {};
  const nextStepsPayload = workflow.next_steps || {};
  const gates = audit.gates || [];
  const blockers = audit.blockers || [];
  const nextSteps = audit.next_steps || nextStepsPayload.next_steps || [];
  const artifacts = workflow.artifacts || [];
  const hasAudit = Boolean(workflow.has_gate_audit);
  const routeLabel = route.route || "未路由";
  const ok = Boolean(audit.ok);
  const nextGate = audit.next_gate || nextStepsPayload.next_gate || "先运行任务路由或 Gate 审计。";

  el.gateSummary.innerHTML = `
    <span class="pill ${hasAudit ? (ok ? "ok" : "bad") : ""}">${hasAudit ? (ok ? "可进入下一阶段" : "存在阻塞") : "未检查"}</span>
    <strong>${safe(routeLabel)}</strong>
    <small>${safe(nextGate)}</small>
  `;

  if (state.activeGateId && !gates.some((gate) => gate.id === state.activeGateId)) {
    state.activeGateId = "";
  }
  if (!state.activeGateId && gates.length) {
    const firstFailed = gates.find((gate) => !gate.ok);
    state.activeGateId = firstFailed ? firstFailed.id : gates[0].id;
  }

  el.gateRows.innerHTML = gates.length ? gates.map((gate) => `
    <button class="gate-row ${gate.ok ? "pass" : gate.severity === "warn" ? "warn" : "fail"} ${state.activeGateId === gate.id ? "active" : ""}" type="button" data-gate-id="${safe(gate.id)}">
      <span>${gate.ok ? "通过" : gate.severity === "warn" ? "提醒" : "阻塞"}</span>
      <strong>${safe(gate.title || gate.description || gate.id)}</strong>
      <small>${safe(gate.current)} / ${safe(gate.target)}</small>
    </button>
  `).join("") : `<div class="empty-state">还没有 Gate 审计结果。</div>`;

  el.nextStepRows.innerHTML = nextSteps.length ? nextSteps.map((step) => {
    const action = nextStepActionForGate(step.gate_id);
    return `
    <div class="next-step-row">
      <span>${safe(step.order || "")}</span>
      <div>
        <strong>${safe(step.gate_title || step.gate_id)}</strong>
        <small>人工：${safe(step.human_action)}</small>
        <small>Agent：${safe(step.agent_action)}</small>
      </div>
      ${action
        ? `<button class="mini-btn next-step-action" type="button" data-next-step-action="${safe(action.id)}">${safe(action.label)}</button>`
        : `<em>${step.can_agent_execute ? "需补输入" : "需人工"}</em>`}
    </div>
  `;
  }).join("") : `<div class="empty-state">${hasAudit && ok ? "当前没有阻塞项。" : "运行 Gate 审计后显示下一步。"}</div>`;

  if (blockers.length) {
    el.projectStatus.textContent = `Blocked: ${blockers.length} gate(s)`;
  }
  renderGateDetails(workflow.gate_details || {});
  renderWorkflowArtifacts(artifacts);
}

function renderGateDetails(details) {
  const selected = details[state.activeGateId] || {};
  const records = selected.records || [];
  const summary = selected.gate_id ? `
    <div class="detail-row gate-detail-summary-row">
      <span class="pill ${selected.ok ? "ok" : selected.severity === "warn" ? "" : "bad"}">${safe(selected.status || "unknown")}</span>
      <div>
        <strong>${safe(selected.title || selected.gate_id)}</strong>
        <small>${safe(selected.why || "")}</small>
        <small>人工：${safe(selected.next_human_action || "")}</small>
        <small>Agent：${safe(selected.next_agent_action || "")}</small>
      </div>
    </div>
  ` : "";
  const rows = records.length ? records.map((record) => `
    <div class="detail-row">
      <span class="pill">${safe(record.record_type)}</span>
      <div>
        <strong>${safe(record.title || record.record_id)}</strong>
        <small>${safe(record.record_ref || record.record_id)}</small>
        <small>${safe(record.action)}</small>
      </div>
    </div>
  `).join("") : `<div class="empty-state">${state.activeGateId ? "这个 Gate 没有具体待处理记录。" : "点击 Gate 查看具体记录。"}</div>`;
  el.gateDetailRows.innerHTML = summary + rows;
}

function renderWorkflowArtifacts(artifacts) {
  el.workflowArtifactRows.innerHTML = artifacts.length ? artifacts.map((artifact) => `
    <div class="artifact-row ${artifact.complete ? "complete" : "missing"}">
      <span class="pill ${artifact.complete ? "ok" : "bad"}">${artifact.complete ? "完整" : "缺失"}</span>
      <div>
        <strong>${safe(artifact.title || artifact.id)}</strong>
        <small>JSON：${artifact.json_path ? `${artifact.json_exists ? "存在" : "缺失"} · ${safe(artifact.json_path)}` : "不需要"}</small>
        <small>Markdown：${artifact.markdown_exists ? "存在" : "缺失"} · ${safe(artifact.markdown_path)}</small>
      </div>
    </div>
  `).join("") : `<div class="empty-state">还没有流程产物状态。</div>`;
}

function renderReviewQueue(queue) {
  el.reviewQueueRows.innerHTML = queue.length ? queue.map((item) => `
    <div class="review-queue-row" data-review-item="${safe(item.id)}">
      <span class="pill ${item.item_type === "poor_source_evidence" ? "bad" : ""}">${safe(item.priority || item.item_type)}</span>
      <div>
        <strong>${safe(item.title)}</strong>
        <small>${safe(item.item_type)} · ${safe(item.record_ref || item.id)}</small>
        <small>${safe(item.summary)}</small>
        <small>${safe(item.action)}</small>
      </div>
      <div class="row-actions">
        ${reviewQueueActions(item)}
      </div>
    </div>
  `).join("") : `<div class="empty-state">当前没有待人工审核项。</div>`;
}

function reviewQueueActions(item) {
  if (item.item_type === "source_quality") {
    return `
      <select class="review-source-quality" data-source-quality-select="${safe(item.source_id)}">
        <option value="good">good</option>
        <option value="mixed">mixed</option>
        <option value="poor">poor</option>
        <option value="unknown">unknown</option>
      </select>
      <input class="review-decision-note" data-review-note="${safe(item.id)}" placeholder="审核备注 / 质量理由" />
      <button class="mini-btn" type="button" data-source-review-apply="${safe(item.source_id)}">记录审核</button>
      <button class="mini-btn" type="button" data-queue-focus="sources">定位</button>
    `;
  }
  if (item.item_type === "candidate_evidence" || item.item_type === "poor_source_evidence") {
    return `
      <select class="review-evidence-status" data-evidence-status-select="${safe(item.evidence_id)}">
        <option value="verified">verified</option>
        <option value="rejected">rejected</option>
        <option value="candidate">candidate</option>
      </select>
      <select class="review-evidence-relation" data-evidence-relation-select="${safe(item.evidence_id)}">
        <option value="">keep relation</option>
        <option value="supports">supports</option>
        <option value="contradicts">contradicts</option>
        <option value="context">context</option>
        <option value="unknown">unknown</option>
      </select>
      <select class="review-evidence-confidence" data-evidence-confidence-select="${safe(item.evidence_id)}">
        <option value="">keep confidence</option>
        <option value="high">high</option>
        <option value="medium">medium</option>
        <option value="low">low</option>
        <option value="unknown">unknown</option>
      </select>
      <input class="review-decision-note" data-review-note="${safe(item.id)}" placeholder="审核备注 / 通过或拒绝理由" />
      <button class="mini-btn" type="button" data-evidence-review-apply="${safe(item.evidence_id)}">记录审核</button>
      <button class="mini-btn" type="button" data-queue-focus="evidence">定位</button>
    `;
  }
  if (item.item_type === "claim_without_evidence" || item.item_type === "missing_counter_evidence") {
    return `<button class="mini-btn" type="button" data-queue-focus="evidence" data-queue-claim-id="${safe(item.claim_id || item.refs?.claim_id || item.id)}">补证据</button>`;
  }
  return `<button class="mini-btn" type="button" data-queue-focus="gate">查看 Gate</button>`;
}

function renderSourceInbox(inbox) {
  const items = inbox?.items || [];
  el.sourceInboxRows.innerHTML = items.length ? items.map((item) => `
    <div class="review-queue-row">
      <span class="pill ${item.import_status === "rejected" ? "bad" : item.import_status === "imported" ? "ok" : ""}">${safe(item.import_status)}</span>
      <div>
        <strong>${safe(item.title)}</strong>
        <small>${safe(item.kind)} · ${safe(item.source_tool || "manual")}</small>
        <small>${safe(item.location || item.url || item.path)}</small>
      </div>
      <div class="row-actions">
        <button class="mini-btn" type="button" data-inbox-import="${safe(item.id)}">导入来源</button>
        <button class="mini-btn" type="button" data-inbox-reject="${safe(item.id)}">拒绝</button>
      </div>
    </div>
  `).join("") : `<div class="empty-state">当前没有候选资料。搜索、网页、视频结果可以先进入这里。</div>`;
}

function nextStepActionForGate(gateId) {
  const actions = {
    task_route_present: { id: "route-task", label: "运行路由" },
    research_plan_present: { id: "build-plan", label: "生成计划" },
    sources_present: { id: "focus-sources", label: "去添加来源" },
    source_quality_reviewed: { id: "focus-source-review", label: "去标注来源" },
    claims_present: { id: "focus-claims", label: "去添加主张" },
    evidence_present: { id: "focus-evidence", label: "去补证据" },
    verified_evidence_present: { id: "focus-evidence-review", label: "去审核证据" },
    human_reviews_recorded: { id: "focus-review", label: "去记录审核" },
    multi_perspective_review_present: { id: "multi-review", label: "多视角审查" },
    reader_persona_review_present: { id: "persona-review", label: "读者盲测" },
    result_file_chain_complete: { id: "audit-final", label: "检查终稿链" },
    counter_evidence_checked: { id: "counter-plan", label: "补反证任务" },
  };
  return actions[gateId] || null;
}

async function runNextStepAction(actionId) {
  if (actionId === "route-task") {
    await runWorkflowAction("/api/route-research-task", { question: el.question.value, material_hint: el.materialHint.value }, "任务路由已生成");
    return;
  }
  if (actionId === "build-plan" || actionId === "counter-plan") {
    await buildPlan(true);
    return;
  }
  if (actionId === "multi-review") {
    await runWorkflowAction("/api/multi-perspective-review", {}, "多视角审查已生成");
    return;
  }
  if (actionId === "persona-review") {
    await runWorkflowAction("/api/reader-persona-review", {}, "读者盲测已生成");
    return;
  }
  if (actionId === "audit-final") {
    await runWorkflowAction("/api/audit-gates", { target_stage: "final_answer" }, "终稿文件链已检查");
    return;
  }
  const focusTargets = {
    "focus-sources": ["sourcesPanel", "sourceTitle", "请在来源区补充 URL、本地路径或视频资料。"],
    "focus-source-review": ["sourcesPanel", "sourceRows", "请在来源列表中标注 good / mixed / poor。"],
    "focus-claims": ["claimsPanel", "claimText", "请补充需要验证的主张或子问题。"],
    "focus-evidence": ["evidencePanel", "evidenceQuote", "请为主张补充证据摘录或候选证据。"],
    "focus-evidence-review": ["evidencePanel", "evidenceList", "请审核候选证据，通过后才会成为 verified。"],
    "focus-review": ["sourcesPanel", "sourceRows", "请完成来源或证据审核记录。"],
  };
  if (focusTargets[actionId]) {
    const [panelId, controlId, message] = focusTargets[actionId];
    focusPanel(panelId, controlId);
    setNotice(message, "warn");
    return;
  }
  throw new Error(`Unknown next step action: ${actionId}`);
}

function focusPanel(panelId, controlId) {
  const panel = document.querySelector(`#${panelId}`);
  if (!panel) return;
  document.querySelectorAll(".panel.focused-panel").forEach((item) => item.classList.remove("focused-panel"));
  panel.classList.add("focused-panel");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  const control = document.querySelector(`#${controlId}`);
  if (control && typeof control.focus === "function") {
    window.setTimeout(() => control.focus({ preventScroll: true }), 260);
  }
  window.setTimeout(() => panel.classList.remove("focused-panel"), 1800);
}

function renderTools(tools) {
  state.tools = tools;
  el.toolCards.innerHTML = tools.map((tool) => `
    <div class="tool-card">
      <div class="tool-card-header"><strong>${safe(tool.name)}</strong><span class="pill">${safe(tool.status)}</span></div>
      <p>${safe(tool.purpose)}</p>
      <button class="mini-btn" type="button" data-tool-health="${safe(tool.name)}">健康检查</button>
    </div>
  `).join("");
  el.toolHealthList.innerHTML = tools.map((tool) => `<div class="doctor-check"><span>${safe(tool.name)}</span><span class="pill">registered</span></div>`).join("");
}

async function loadProject() {
  resetProviderPasteInbox();
  const data = await getJSON(`/api/project?root=${encodeURIComponent(el.root.value)}`);
  renderProject(data);
  if (data.ok && data.project?.question) {
    el.deepQuestion.value = data.project.question;
  }
  await loadExternalReports();
  await loadSourceInbox();
  await loadToolBridgeStatus();
  await loadCompletenessAudit();
  await loadGraphCandidates();
  setNotice(data.ok ? "项目已加载" : "项目未初始化", data.ok ? "ok" : "warn");
}

async function loadSourceInbox() {
  const data = await getJSON(`/api/source-inbox?root=${encodeURIComponent(el.root.value)}`);
  renderSourceInbox(data);
  return data;
}

async function loadTools() {
  const data = await getJSON("/api/tools");
  renderTools(data.tools || []);
  if (state.project?.dashboard && data.health) {
    state.project.dashboard.local_tools = data.health;
    renderDashboard(state.project.dashboard, state.project.overview || {});
  }
}

async function loadToolBridgeStatus() {
  const data = await getJSON(`/api/tool-bridge-status?root=${encodeURIComponent(el.root.value)}`);
  state.bridgeStatus = data;
  renderToolBridgeStatus(data);
  return data;
}

async function loadBridgeRuns(tool = "") {
  const query = new URLSearchParams({ root: el.root.value, limit: "20" });
  if (tool) query.set("tool", tool);
  const data = await getJSON(`/api/bridge-runs?${query.toString()}`);
  renderBridgeRuns(data);
  return data;
}

async function loadCompletenessAudit() {
  const data = await getJSON(`/api/completeness-audit?root=${encodeURIComponent(el.root.value)}`);
  renderCompletenessAudit(data);
  return data;
}

async function loadGraphCandidates() {
  const status = el.graphStatusFilter?.value || "";
  const edgeType = el.graphEdgeTypeFilter?.value || "";
  const query = new URLSearchParams({ root: el.root.value });
  if (status) query.set("status", status);
  if (edgeType) query.set("edge_type", edgeType);
  const data = await getJSON(`/api/graph-candidates?${query.toString()}`);
  renderGraphCandidates(data);
  return data;
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-source-review], [data-source-review-apply], [data-evidence-review], [data-evidence-review-apply], [data-tool-health], [data-next-step-action], [data-gate-id], [data-queue-focus], [data-inbox-import], [data-inbox-reject], [data-workqueue-preview], [data-workqueue-execute], [data-graph-review]");
  if (!target) return;
  const sourceId = target.dataset?.sourceReview;
  const sourceApplyId = target.dataset?.sourceReviewApply;
  const evidenceId = target.dataset?.evidenceReview;
  const evidenceApplyId = target.dataset?.evidenceReviewApply;
  const tool = target.dataset?.toolHealth;
  const nextStepAction = target.dataset?.nextStepAction;
  const gateId = target.dataset?.gateId;
  const queueFocus = target.dataset?.queueFocus;
  const queueClaimId = target.dataset?.queueClaimId;
  const inboxImport = target.dataset?.inboxImport;
  const inboxReject = target.dataset?.inboxReject;
  const workQueuePreview = target.dataset?.workqueuePreview;
  const workQueueExecute = target.dataset?.workqueueExecute;
  const graphReview = target.dataset?.graphReview;
  try {
    if (gateId) {
      state.activeGateId = gateId;
      renderGateWorkbench(state.project?.workflow || {});
      return;
    }
    if (nextStepAction) {
      await runNextStepAction(nextStepAction);
    }
    if (queueFocus) {
      const targets = {
        sources: ["sourcesPanel", "sourceRows", "请在来源区处理这条审核项。"],
        evidence: ["evidencePanel", "evidenceList", "请在证据区处理这条审核项。"],
        gate: ["gatePanel", "gateRows", "请查看对应 Gate 详情。"],
      };
      const target = targets[queueFocus] || targets.gate;
      if (queueClaimId && el.evidenceClaim) {
        el.evidenceClaim.value = queueClaimId;
      }
      focusPanel(target[0], target[1]);
      setNotice(queueClaimId ? "已定位到证据区，并预选对应主张；请补充证据摘录或候选证据。" : target[2], "warn");
      return;
    }
    if (sourceId) {
      const data = await postJSON("/api/source/review", { source_id: sourceId, quality: target.dataset.quality, reason: "UI 标注" });
      renderProject(data.state);
      setNotice("来源质量已标注", "ok");
    }
    if (inboxImport) {
      const data = await postJSON("/api/source-inbox/import", { id: inboxImport });
      if (data.state) renderProject(data.state);
      renderSourceInbox(data.source_inbox);
      setNotice("收件箱资料已导入为候选来源，仍需人工标注质量。", "ok");
    }
    if (inboxReject) {
      const data = await postJSON("/api/source-inbox/reject", { id: inboxReject, note: "UI 拒绝" });
      renderSourceInbox(data.source_inbox);
      setNotice("收件箱资料已拒绝。", "ok");
    }
    if (workQueuePreview || workQueueExecute) {
      const taskId = workQueuePreview || workQueueExecute;
      const data = await postJSON("/api/run-work-queue-item", { id: taskId, execute: Boolean(workQueueExecute), timeout_seconds: 120 });
      renderWorkQueue(data.work_queue || data.result?.queue);
      if (data.state) renderProject(data.state);
      el.output.textContent = JSON.stringify(data.result, null, 2);
      setNotice(workQueueExecute ? "队列工具动作已执行，结果已写入 artifact。" : "队列工具动作已预览，未执行。", data.ok ? "ok" : "warn");
    }
    if (graphReview) {
      const row = target.closest("[data-graph-row]");
      const data = await postJSON("/api/review-graph-candidate", {
        from_id: row?.dataset?.fromId || "",
        to_id: row?.dataset?.toId || "",
        status: graphReview,
        note: row?.querySelector("[data-graph-note]")?.value || "",
      });
      renderGraphCandidates(data.graph);
      if (data.state) renderProject(data.state);
      setNotice(graphReview === "accepted" ? "图谱边已接受。" : "图谱边已拒绝。", "ok");
    }
    if (sourceApplyId) {
      const quality = document.querySelector(`[data-source-quality-select="${CSS.escape(sourceApplyId)}"]`)?.value || "unknown";
      const note = reviewNoteFor(target) || "UI 审核队列标注";
      const data = await postJSON("/api/review-source", { source_id: sourceApplyId, quality, reason: note });
      renderProject(data.state);
      setNotice("来源审核备注已记录", "ok");
    }
    if (evidenceId) {
      const data = await postJSON("/api/evidence/review", { evidence_id: evidenceId, status: target.dataset.status });
      renderProject(data.state);
      setNotice("证据审核已更新", "ok");
    }
    if (evidenceApplyId) {
      const status = document.querySelector(`[data-evidence-status-select="${CSS.escape(evidenceApplyId)}"]`)?.value || "candidate";
      const relation = document.querySelector(`[data-evidence-relation-select="${CSS.escape(evidenceApplyId)}"]`)?.value || "";
      const confidence = document.querySelector(`[data-evidence-confidence-select="${CSS.escape(evidenceApplyId)}"]`)?.value || "";
      const notes = reviewNoteFor(target);
      const data = await postJSON("/api/review-evidence", { evidence_id: evidenceApplyId, status, relation, confidence, notes });
      renderProject(data.state);
      setNotice("证据审核备注已记录", "ok");
    }
    if (tool) {
      const data = await postJSON("/api/tool-health", { tool });
      el.output.textContent = JSON.stringify(data, null, 2);
      setNotice(`${tool} 检查完成`, data.ok ? "ok" : "warn");
    }
  } catch (error) {
    setNotice(error.message, "error");
  }
});

function reviewNoteFor(target) {
  const row = target.closest("[data-review-item]");
  const input = row?.querySelector("[data-review-note]");
  return input ? input.value.trim() : "";
}

el.loadProject.addEventListener("click", () => loadProject().catch((error) => setNotice(error.message, "error")));
el.initProject.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/project/init", { question: el.question.value });
    renderProject(data.state);
    if (data.state?.project?.question) {
      el.deepQuestion.value = data.state.project.question;
    }
    clearExternalResearcherInboxForNewQuestion();
    setNotice("项目已创建", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
async function buildPlan(addClaims) {
  const data = await postJSON("/api/research-plan", { question: el.question.value, add_claims: addClaims, write: true });
  renderProject(data.state);
  el.output.textContent = JSON.stringify(data.plan, null, 2);
  setNotice(addClaims ? "研究计划已生成，初始主张已写入" : "研究计划已生成", "ok");
}

async function runSearch(importResults) {
  const data = await postJSON("/api/ai-research-search", {
    query: el.searchQuery.value,
    mode: el.searchMode.value,
    max_results: Number(el.searchMaxResults.value || 8),
    base_url: el.aiResearchBaseUrl.value,
    import_results: importResults,
    fetch: true,
    timeout_seconds: 180,
  });
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderAiResearchBridge(data.result, importResults ? "executed_import" : "executed_preview");
  setNotice(importResults ? "搜索完成并尝试导入" : "搜索完成，未导入", data.ok ? "ok" : "warn");
}

async function planSearch(importResults = false) {
  const data = await postJSON("/api/ai-research-plan", {
    query: el.searchQuery.value,
    mode: el.searchMode.value,
    max_results: Number(el.searchMaxResults.value || 8),
    base_url: el.aiResearchBaseUrl.value,
    import_results: importResults,
    fetch: true,
  });
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderAiResearchBridge(data.result, "planned");
  setNotice("搜索调度计划已生成", "ok");
}

async function importAiResearchResultPath() {
  const data = await postJSON("/api/import-ai-research-result", { path: el.aiResearchResultPath.value.trim() });
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderAiResearchBridge(data.result, "imported_json");
  setNotice("本地 ai-research result JSON 已导入为候选材料，仍需人工审核。", "ok");
}

function renderAiResearchBridge(result, phase) {
  const ok = Boolean(result?.ok);
  const status = phase === "planned" ? "计划" : ok ? "可用" : "失败";
  const endpoint = result?.endpoint || "";
  const baseUrl = result?.base_url || "";
  const query = result?.query || result?.payload?.topic || "";
  const counts = result?.imported?.counts || {};
  el.aiResearchBridgeSummary.innerHTML = `
    <span class="pill ${ok ? "ok" : phase === "planned" ? "" : "bad"}">${safe(status)}</span>
    <strong>${safe(baseUrl || "ai-research-workflow")}</strong>
    <small>${safe(endpoint || result?.next_action || result?.failure_next_action || "等待计划或状态检查")}</small>
  `;
  const rows = [];
  if (query) rows.push(["Query", query]);
  if (result?.payload) rows.push(["Payload", JSON.stringify(result.payload)]);
  if (result?.error) rows.push(["Error", result.error]);
  if (result?.next_action || result?.failure_next_action) rows.push(["Next", result.next_action || result.failure_next_action]);
  if (result?.run_path) rows.push(["Run", result.run_path]);
  if (Object.keys(counts).length) rows.push(["Imported", `sources ${counts.sources || 0}, claims ${counts.claims || 0}, evidence ${counts.evidence || 0}`]);
  el.aiResearchResultRows.innerHTML = rows.length ? rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("") : `<div class="empty-state">暂无搜索桥接结果。</div>`;
}

function vanePayload(importResults) {
  return {
    query: el.searchQuery.value,
    sources: el.vaneSources.value,
    optimization_mode: el.vaneOptimization.value,
    base_url: el.vaneBaseUrl.value,
    chat_model_key: el.vaneChatModelKey.value,
    embedding_model_key: el.vaneEmbeddingModelKey.value,
    import_results: importResults,
    timeout_seconds: 180,
  };
}

async function runVaneSearch(importResults) {
  const data = await postJSON("/api/vane-perplexica-search", vanePayload(importResults));
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderVaneBridge(data.result, importResults ? "executed_import" : "executed_preview");
  setNotice(importResults ? "Vane/Perplexica 已导入候选来源" : "Vane/Perplexica 搜索完成，未导入", data.ok ? "ok" : "warn");
}

async function planVaneSearch(importResults = false) {
  const data = await postJSON("/api/vane-perplexica-plan", vanePayload(importResults));
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderVaneBridge(data.result, "planned");
  setNotice("Vane/Perplexica 候选搜索计划已生成", data.ok ? "ok" : "warn");
}

function renderVaneBridge(result, phase) {
  const ok = Boolean(result?.ok);
  const status = phase === "planned" ? "计划" : ok ? "可用" : "失败";
  const baseUrl = result?.base_url || "";
  const counts = result?.imported?.counts || result?.counts || {};
  const candidateSources = result?.result?.sources || result?.sources || [];
  el.vaneBridgeSummary.innerHTML = `
    <span class="pill ${ok ? "ok" : phase === "planned" ? "" : "bad"}">${safe(status)}</span>
    <strong>${safe(baseUrl || "Vane / Perplexica")}</strong>
    <small>${safe(result?.failure_next_action || result?.recovery_hint || result?.error || "candidate context only")}</small>
  `;
  const rows = [];
  if (result?.query) rows.push(["Query", result.query]);
  if (result?.payload) rows.push(["Payload", JSON.stringify(result.payload)]);
  if (result?.json_path) rows.push(["Raw", result.json_path]);
  if (result?.markdown_path) rows.push(["Report", result.markdown_path]);
  if (Object.keys(counts).length) rows.push(["Imported", `sources ${counts.sources || 0}, claims ${counts.claims || 0}, evidence ${counts.evidence || 0}`]);
  if (candidateSources.length) rows.push(["Returned sources", String(candidateSources.length)]);
  if (result?.error) rows.push(["Error", result.error]);
  el.vaneResultRows.innerHTML = rows.length ? rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("") : `<div class="empty-state">暂无 Vane/Perplexica 桥接结果。</div>`;
}

async function planExternalResearcher() {
  const data = await postJSON("/api/external-researcher-plan", externalResearcherPayload());
  if (data.state) renderProject(data.state);
  renderExternalResearcherPlan(data.result);
  el.output.textContent = data.result.deep_research_prompt || JSON.stringify(data.result, null, 2);
  setNotice("外部研究员提示词已生成。可以自动运行，也可以手动复制到网页端。", "ok");
}

function externalResearcherPayload(extra = {}) {
  return {
    question: el.question.value,
    clarification_answers: el.externalClarifications.value,
    providers: el.externalProviders.value,
    source_policy: el.externalSourcePolicy.value,
    output_language: el.externalOutputLanguage.value || "中文",
    profile_config_path: el.externalProfileConfigPath.value,
    followup_wait_seconds: Number(el.externalFollowupWaitSeconds.value || 10),
    max_wait_seconds: Number(el.externalMaxWaitSeconds.value || 900),
    ...extra,
  };
}

async function planExternalResearcherAutomation() {
  const data = await postJSON("/api/external-researcher-automation-plan", externalResearcherPayload());
  if (data.state) renderProject(data.state);
  renderExternalResearcherPlan(data.result);
  state.externalAutomationPlanPath = data.result.json_path || "";
  el.externalAutomationOutput.value = [
    "自动化计划已生成。",
    "",
    `Plan JSON: ${data.result.json_path}`,
    `Plan Markdown: ${data.result.markdown_path}`,
    `Persistent profile root: ${data.result.persistent_profile_root || ""}`,
    "",
    "Providers:",
    ...(data.result.provider_profiles || []).map((profile) => `- ${profile.provider}: ${profile.ready ? profile.url : "未配置 URL"}`),
    "",
    "运行会打开可见浏览器窗口，使用各 provider 的持久 profile。首次需要你登录一次。",
  ].join("\n");
  el.output.textContent = el.externalAutomationOutput.value;
  setNotice("外部研究员自动化计划已生成。", "ok");
}

async function runExternalResearcherAutomation() {
  const payload = externalResearcherPayload({
    automation_plan: state.externalAutomationPlanPath,
    import_as_source: true,
    dry_run: false,
    headless: false,
  });
  el.externalAutomationOutput.value = "正在启动浏览器自动执行。若网页端要求登录、验证码或适配器失效，会在运行结果里标出接管点。";
  setNotice("正在运行外部研究员自动化，深度研究可能需要几分钟。", "warn");
  const data = await postJSON("/api/external-researcher-automation-run", payload);
  if (data.state) renderProject(data.state);
  renderExternalReports(data.reports);
  state.externalAutomationPlanPath = data.result.plan_path || state.externalAutomationPlanPath;
  const rows = (data.result.results || []).map((result) => [
    `## ${result.provider}`,
    `- Status: ${result.status}`,
    `- URL: ${result.url || ""}`,
    `- Error: ${result.error || ""}`,
    `- Report chars: ${(result.report_text || "").length}`,
  ].join("\n"));
  el.externalAutomationOutput.value = [
    `Automation run: ${data.result.markdown_path || ""}`,
    `Imported reports: ${data.result.imported_count || 0}`,
    "",
    ...rows,
  ].join("\n");
  el.output.textContent = el.externalAutomationOutput.value;
  setNotice(data.ok ? "外部研究员自动化已完成并导入报告。" : "自动化运行需要人工接管或适配器修正。", data.ok ? "ok" : "warn");
}

async function checkExternalResearcherAutomation(live = false) {
  const payload = externalResearcherPayload({
    automation_plan: state.externalAutomationPlanPath,
    live,
    headless: false,
    timeout_seconds: 30,
  });
  setNotice(live ? "正在打开网页做 live 预检，不会提交研究任务。" : "正在做配置预检。", "warn");
  const data = await postJSON("/api/external-researcher-automation-check", payload);
  if (data.state) renderProject(data.state);
  const rows = (data.result.results || []).map((result) => [
    `## ${result.provider}`,
    `- Status: ${result.status}`,
    `- URL: ${result.url || ""}`,
    `- Input visible: ${result.input_visible ?? ""}`,
    `- Mode labels: ${(result.activation_texts_present || []).join(", ")}`,
    `- Blockers: ${(result.blockers || []).join(", ")}`,
    `- Recovery: ${result.recovery_hint || result.error || ""}`,
  ].join("\n"));
  el.externalAutomationOutput.value = [
    `Preflight: ${data.result.markdown_path || ""}`,
    `Live: ${data.result.live}`,
    `Blocking providers: ${data.result.blocking_count || 0}/${data.result.provider_count || 0}`,
    "",
    ...rows,
  ].join("\n");
  el.output.textContent = el.externalAutomationOutput.value;
  setNotice(data.ok ? "外部研究员预检通过。" : "预检发现需要人工接管或适配器修正。", data.ok ? "ok" : "warn");
}

async function prepareExternalResearcherLoginProfiles(live = false) {
  const payload = externalResearcherPayload({
    automation_plan: state.externalAutomationPlanPath,
    live,
    headless: false,
    timeout_seconds: 45,
    keep_open_seconds: 600,
  });
  setNotice(live ? "正在打开登录窗口；请完成登录后关闭窗口。" : "正在生成登录窗口计划。", live ? "warn" : "ok");
  const data = await postJSON("/api/external-researcher-login-profiles", payload);
  if (data.state) renderProject(data.state);
  const rows = (data.result.results || []).map((result) => [
    `## ${result.provider}`,
    `- Status: ${result.status}`,
    `- URL: ${result.url || ""}`,
    `- Profile: ${result.user_data_dir || ""}`,
    `- Error: ${result.error || result.navigation_error || ""}`,
    `- Recovery: ${result.recovery_hint || ""}`,
  ].join("\n"));
  el.externalAutomationOutput.value = [
    `Login profile prep: ${data.result.markdown_path || ""}`,
    `Live: ${data.result.live}`,
    `Provider windows: ${data.result.provider_count || 0}`,
    `Keep open seconds: ${data.result.keep_open_seconds || ""}`,
    "",
    ...rows,
  ].join("\n");
  el.output.textContent = el.externalAutomationOutput.value;
  setNotice(live ? "登录窗口已完成或已超时关闭。" : "登录窗口计划已生成。", data.ok ? "ok" : "warn");
}

async function writeExternalProfileTemplate() {
  const data = await postJSON("/api/external-researcher-profile-template", {});
  if (data.state) renderProject(data.state);
  el.externalProfileConfigPath.value = data.result.path || el.externalProfileConfigPath.value;
  el.externalAutomationOutput.value = [
    "网页适配器模板已写出。",
    "",
    data.result.path,
    "",
    "你可以在这里改 provider URL、深度研究按钮文字、输入框/发送按钮/报告抽取选择器。",
  ].join("\n");
  setNotice("适配器模板已生成。网页改版时优先改这个 JSON。", "ok");
}

function renderExternalResearcherPlan(result) {
  const ok = Boolean(result?.ok);
  el.externalPromptOutput.value = result?.deep_research_prompt || "";
  el.externalBridgeSummary.innerHTML = `
    <span class="pill ${ok ? "ok" : "bad"}">${ok ? "已计划" : "失败"}</span>
    <strong>${safe((result?.providers || []).join(" / ") || "External web researchers")}</strong>
    <small>${safe(result?.markdown_path || "provider reports are candidate context only")}</small>
  `;
}

async function submitExternalFollowup(manual = false) {
  const data = await postJSON("/api/external-researcher-followup", {
    followup_question: el.externalFollowupQuestion.value,
    manual_answer: manual ? el.externalManualAnswer.value : "",
    original_question: el.question.value,
    source_policy: el.externalSourcePolicy.value,
    auto_after_seconds: 10,
  });
  if (data.state) renderProject(data.state);
  el.externalFollowupAnswerOutput.value = data.result.answer || "";
  el.output.textContent = data.result.answer || JSON.stringify(data.result, null, 2);
  setNotice(data.result.answer_source === "manual" ? "追问人工回答已保存。" : "已使用保守默认回答处理追问。", data.result.answer_source === "manual" ? "ok" : "warn");
  stopExternalCountdown();
}

function startExternalCountdown(seconds = 10) {
  stopExternalCountdown();
  let remaining = seconds;
  el.externalFollowupCountdown.textContent = `${remaining}s`;
  setNotice("等待人工介入：10 秒内可提交人工回答，超时使用默认回答。", "warn");
  state.externalFollowupTimer = window.setInterval(async () => {
    remaining -= 1;
    el.externalFollowupCountdown.textContent = `${remaining}s`;
    if (remaining <= 0) {
      stopExternalCountdown();
      try {
        await submitExternalFollowup(false);
      } catch (error) {
        setNotice(error.message, "error");
      }
    }
  }, 1000);
}

function stopExternalCountdown() {
  if (state.externalFollowupTimer) {
    window.clearInterval(state.externalFollowupTimer);
    state.externalFollowupTimer = null;
  }
  if (el.externalFollowupCountdown) {
    el.externalFollowupCountdown.textContent = "idle";
  }
}

async function importExternalReport() {
  const data = await postJSON("/api/external-researcher-report", {
    provider: el.externalReportProvider.value,
    report_url: el.externalReportUrl.value,
    notes: el.externalReportNotes.value,
    prompt_text: el.externalPromptOutput.value,
    report_text: el.externalReportText.value,
    import_as_source: true,
  });
  if (data.state) renderProject(data.state);
  renderExternalReports(data.reports);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  el.externalReportText.value = "";
  setNotice("外部研究员报告已保存为候选上下文，并作为 unknown 来源导入。", "ok");
}

async function loadExternalReports() {
  const data = await getJSON(`/api/external-researcher-reports?root=${encodeURIComponent(el.root.value)}`);
  renderExternalReports(data);
  return data;
}

function renderExternalReports(payload) {
  const reports = payload?.reports || [];
  el.externalReportRows.innerHTML = reports.length ? reports.map((report) => `
    <div class="bridge-result-row">
      <span>${safe(report.provider)}</span>
      <strong>${safe(report.markdown_path || report.json_path)}</strong>
      <small>${safe(report.report_url || report.notes || "")}</small>
    </div>
  `).join("") : `<div class="empty-state">还没有保存外部深度研究报告。</div>`;
  renderProviderPasteReports(payload);
}

async function exportExternalBundle() {
  const data = await postJSON("/api/external-researcher-export", {});
  if (data.state) renderProject(data.state);
  renderExternalReports(data.reports);
  el.output.textContent = [
    "# 外部研究员汇总已导出",
    "",
    `- Markdown: ${data.result.markdown_path}`,
    `- JSON: ${data.result.json_path}`,
    `- Reports: ${data.result.report_count}`,
  ].join("\n");
  setNotice("外部研究员汇总 Markdown 已导出。它仍是候选上下文，不是验证后的最终答案。", "ok");
  return data;
}

function renderDeepMergeResult(result, selectedCount = 0) {
  el.deepMergeResult.innerHTML = `
    <span class="pill ok">done</span>
    <div>
      <strong>已整合 ${selectedCount || result?.report_count || 0} 份回答</strong>
      <small>Markdown: <code>${safe(result?.markdown_path || "")}</code></small>
      <small>JSON: <code>${safe(result?.json_path || "")}</code></small>
      <small>Reports: ${safe(String(result?.report_count || 0))}</small>
    </div>
  `;
}

el.deepQuestion.addEventListener("input", () => {
  el.question.value = el.deepQuestion.value;
});
el.question.addEventListener("input", () => {
  el.deepQuestion.value = el.question.value;
});
el.deepClarifications.addEventListener("input", () => {
  el.externalClarifications.value = el.deepClarifications.value;
});
el.deepSourcePolicy.addEventListener("input", () => {
  el.externalSourcePolicy.value = el.deepSourcePolicy.value;
});
document.querySelectorAll(".deep-provider-checkbox").forEach((input) => {
  input.addEventListener("change", syncDeepProvidersToExternalField);
});
document.querySelectorAll("[data-paste-provider]").forEach((button) => {
  button.addEventListener("click", () => pasteProviderAnswerFromClipboard(button).catch((error) => setNotice(error.message, "error")));
});
document.querySelectorAll("[data-provider-report]").forEach((textarea) => {
  textarea.addEventListener("input", () => scheduleProviderDraftAutosave(textarea));
  textarea.addEventListener("paste", () => window.setTimeout(() => scheduleProviderDraftAutosave(textarea), 0));
  textarea.addEventListener("blur", () => autosaveProviderDraft(textarea.dataset.providerReport || "", textarea.closest("[data-provider-card]")?.querySelector("[data-paste-provider]")?.dataset.pasteUrl || "", textarea.value).catch((error) => setNotice(error.message, "error")));
});
el.selectCoreProviders.addEventListener("click", () => setProviderSelection("core"));
el.selectAllProviders.addEventListener("click", () => setProviderSelection("all"));
el.clearProviders.addEventListener("click", () => setProviderSelection("none"));
el.deepInitProject.addEventListener("click", () => initProjectFromDeepLaunch().catch((error) => setNotice(error.message, "error")));
el.deepPreparePlan.addEventListener("click", () => deepPreparePlan().catch((error) => setNotice(error.message, "error")));
el.deepCopyPrompt.addEventListener("click", () => copyDeepResearchPrompt().catch((error) => setNotice(error.message, "error")));
el.deepOpenLogin.addEventListener("click", () => deepOpenLoginWindows().catch((error) => setNotice(error.message, "error")));
el.deepPreflight.addEventListener("click", () => deepPreflightWindows().catch((error) => setNotice(error.message, "error")));
el.deepRunAutomation.addEventListener("click", () => deepRunLiveAutomation().catch((error) => setNotice(error.message, "error")));
el.deepExportMarkdown.addEventListener("click", () => exportExternalBundle().catch((error) => setNotice(error.message, "error")));
el.deepImportManualReport.addEventListener("click", () => importManualDeepReport().catch((error) => setNotice(error.message, "error")));
el.deepMergeWhenComplete.addEventListener("click", () => mergeArchivedProviderReports().catch((error) => setNotice(error.message, "error")));
updateProviderPasteProgress();

el.plan.addEventListener("click", () => buildPlan(false).catch((error) => setNotice(error.message, "error")));
el.planAddClaims.addEventListener("click", () => buildPlan(true).catch((error) => setNotice(error.message, "error")));
el.aiResearchStatus.addEventListener("click", async () => {
  try {
    const query = el.aiResearchBaseUrl.value ? `?base_url=${encodeURIComponent(el.aiResearchBaseUrl.value)}` : "";
    const data = await getJSONLoose(`/api/ai-research-status${query}`);
    el.output.textContent = JSON.stringify(data, null, 2);
    renderAiResearchBridge(data, "status");
    setNotice("搜索服务状态已检查", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.searchPlan.addEventListener("click", () => planSearch(false).catch((error) => setNotice(error.message, "error")));
el.searchPreview.addEventListener("click", () => runSearch(false).catch((error) => setNotice(error.message, "error")));
el.searchImport.addEventListener("click", () => runSearch(true).catch((error) => setNotice(error.message, "error")));
el.searchRuns.addEventListener("click", () => loadBridgeRuns("ai-research-workflow").then(() => setNotice("最近搜索 run 已刷新。", "ok")).catch((error) => setNotice(error.message, "error")));
el.importAiResearchResult.addEventListener("click", () => importAiResearchResultPath().catch((error) => setNotice(error.message, "error")));
el.vaneStatus.addEventListener("click", async () => {
  try {
    const query = el.vaneBaseUrl.value ? `?base_url=${encodeURIComponent(el.vaneBaseUrl.value)}` : "";
    const data = await getJSONLoose(`/api/vane-perplexica-status${query}`);
    el.output.textContent = JSON.stringify(data, null, 2);
    renderVaneBridge(data, "status");
    setNotice("Vane/Perplexica 状态已检查", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.vanePlan.addEventListener("click", () => planVaneSearch(false).catch((error) => setNotice(error.message, "error")));
el.vanePreview.addEventListener("click", () => runVaneSearch(false).catch((error) => setNotice(error.message, "error")));
el.vaneImport.addEventListener("click", () => runVaneSearch(true).catch((error) => setNotice(error.message, "error")));
el.externalPlan.addEventListener("click", () => planExternalResearcher().catch((error) => setNotice(error.message, "error")));
el.externalAutomationPlan.addEventListener("click", () => planExternalResearcherAutomation().catch((error) => setNotice(error.message, "error")));
el.externalAutomationCheck.addEventListener("click", () => checkExternalResearcherAutomation(false).catch((error) => setNotice(error.message, "error")));
el.externalAutomationLiveCheck.addEventListener("click", () => checkExternalResearcherAutomation(true).catch((error) => setNotice(error.message, "error")));
el.externalLoginPrepPlan.addEventListener("click", () => prepareExternalResearcherLoginProfiles(false).catch((error) => setNotice(error.message, "error")));
el.externalLoginPrepLive.addEventListener("click", () => prepareExternalResearcherLoginProfiles(true).catch((error) => setNotice(error.message, "error")));
el.externalAutomationRun.addEventListener("click", () => runExternalResearcherAutomation().catch((error) => setNotice(error.message, "error")));
el.externalProfileTemplate.addEventListener("click", () => writeExternalProfileTemplate().catch((error) => setNotice(error.message, "error")));
el.externalListReports.addEventListener("click", () => loadExternalReports().then(() => setNotice("外部报告列表已刷新。", "ok")).catch((error) => setNotice(error.message, "error")));
el.externalExport.addEventListener("click", () => exportExternalBundle().catch((error) => setNotice(error.message, "error")));
el.externalStartCountdown.addEventListener("click", () => startExternalCountdown(Number(el.externalFollowupWaitSeconds.value || 10)));
el.externalManualAnswerBtn.addEventListener("click", () => submitExternalFollowup(true).catch((error) => setNotice(error.message, "error")));
el.externalAutoAnswer.addEventListener("click", () => submitExternalFollowup(false).catch((error) => setNotice(error.message, "error")));
el.externalImportReport.addEventListener("click", () => importExternalReport().catch((error) => setNotice(error.message, "error")));

async function runWorkflowAction(url, payload, doneMessage) {
  const data = await postJSON(url, { write: true, ...payload });
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  setNotice(doneMessage, "ok");
}

el.routeTask.addEventListener("click", () => runWorkflowAction("/api/route-research-task", { question: el.question.value, material_hint: el.materialHint.value }, "任务路由已生成").catch((error) => setNotice(error.message, "error")));
el.gateAudit.addEventListener("click", () => runWorkflowAction("/api/audit-gates", { target_stage: el.targetStage.value }, "Gate 审计已生成").catch((error) => setNotice(error.message, "error")));
el.perspectiveReview.addEventListener("click", () => runWorkflowAction("/api/multi-perspective-review", {}, "多视角审查已生成").catch((error) => setNotice(error.message, "error")));
el.personaReview.addEventListener("click", () => runWorkflowAction("/api/reader-persona-review", {}, "读者盲测已生成").catch((error) => setNotice(error.message, "error")));
el.workflowEngine.addEventListener("click", () => runWorkflowAction("/api/run-workflow-engine", {}, "全流程检查已完成").catch((error) => setNotice(error.message, "error")));

el.addSource.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/source", {
      title: el.sourceTitle.value,
      source_type: el.sourceType.value,
      url: el.sourceUrl.value,
      path: el.sourcePath.value,
      quality: el.sourceQuality.value,
      notes: el.sourceNotes.value,
    });
    renderProject(data.state);
    setNotice("来源已添加", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.addSourceInboxItem.addEventListener("click", async () => {
  try {
    const location = el.sourceInboxLocation.value;
    const data = await postJSON("/api/source-inbox/add", {
      kind: el.sourceInboxKind.value,
      title: el.sourceInboxTitle.value,
      location,
      url: location.startsWith("http") ? location : "",
      path: location.startsWith("http") ? "" : location,
      source_tool: el.sourceInboxTool.value,
      quality_hint: el.sourceInboxQualityHint.value,
    });
    renderSourceInbox(data.source_inbox);
    setNotice("候选资料已加入收件箱。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.refreshSourceInbox.addEventListener("click", () => loadSourceInbox().then(() => setNotice("资料收件箱已刷新。", "ok")).catch((error) => setNotice(error.message, "error")));
async function fetchSelectedSource(createEvidence) {
  const directUrl = el.fetchDirectUrl.value.trim();
  const data = await postJSON("/api/fetch-source-content", {
    source_id: directUrl ? "" : el.fetchSourceSelect.value,
    url: directUrl || "",
    claim_id: createEvidence ? el.fetchClaimSelect.value : "",
    create_candidate_evidence: createEvidence,
    use_browser: Boolean(el.fetchUseBrowser.checked),
    include_raw: Boolean(el.fetchIncludeRaw.checked),
    timeout_seconds: 45,
  });
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderWebFetchBridge(data.result, createEvidence ? "executed_evidence" : "executed_fetch");
  setNotice(createEvidence ? "正文已抓取，候选证据已生成" : "正文已抓取", data.ok ? "ok" : "warn");
}
async function planFetchSelectedSource(createEvidence = false) {
  const directUrl = el.fetchDirectUrl.value.trim();
  const data = await postJSON("/api/fetch-source-plan", {
    source_id: directUrl ? "" : el.fetchSourceSelect.value,
    url: directUrl || "",
    claim_id: createEvidence ? el.fetchClaimSelect.value : "",
    create_candidate_evidence: createEvidence,
    use_browser: Boolean(el.fetchUseBrowser.checked),
    include_raw: Boolean(el.fetchIncludeRaw.checked),
    timeout_seconds: 45,
  });
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderWebFetchBridge(data.result, "planned");
  setNotice("网页抓取计划已生成", data.ok ? "ok" : "warn");
}
function renderWebFetchBridge(result, phase) {
  const ok = Boolean(result?.ok);
  const status = phase === "planned" ? (ok ? "计划" : "缺 URL") : ok ? "完成" : "失败";
  const url = result?.url || result?.source?.url || "";
  const command = Array.isArray(result?.command) ? result.command.join(" ") : "";
  el.webFetchBridgeSummary.innerHTML = `
    <span class="pill ${ok ? "ok" : phase === "planned" ? "bad" : "bad"}">${safe(status)}</span>
    <strong>${safe(result?.tool || "web-content-fetcher")}</strong>
    <small>${safe(url || result?.failure_next_action || "等待抓取计划")}</small>
  `;
  const rows = [];
  if (url) rows.push(["URL", url]);
  if (command) rows.push(["Command", command]);
  if (result?.outputs?.markdown_path) rows.push(["Markdown", result.outputs.markdown_path]);
  if (result?.markdown_path) rows.push(["Markdown", result.markdown_path]);
  if (result?.json_path) rows.push(["JSON", result.json_path]);
  if (result?.run_path) rows.push(["Run", result.run_path]);
  if (result?.candidate_evidence) rows.push(["Evidence", `${result.candidate_evidence.length} candidate item(s)`]);
  if (result?.failure_next_action) rows.push(["Next", result.failure_next_action]);
  el.webFetchResultRows.innerHTML = rows.length ? rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("") : `<div class="empty-state">暂无网页抓取桥接结果。</div>`;
}
el.fetchPlan.addEventListener("click", () => planFetchSelectedSource(false).catch((error) => setNotice(error.message, "error")));
el.fetchSource.addEventListener("click", () => fetchSelectedSource(false).catch((error) => setNotice(error.message, "error")));
el.fetchEvidence.addEventListener("click", () => fetchSelectedSource(true).catch((error) => setNotice(error.message, "error")));

async function planVideoKnowledgeRun() {
  const data = await postJSON("/api/video-knowledge-plan", {
    media_path: el.videoMediaPath.value,
    workspace: el.videoWorkspace.value,
    title: el.videoTitle.value,
    max_frames: Number(el.videoMaxFrames.value || 80),
    build_initial_bundle: true,
  });
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderVideoKnowledgeBridge(data.result, "planned");
  if (!el.videoBundleDir.value && data.result?.expected_artifacts?.review_bundle) {
    el.videoBundleDir.value = data.result.expected_artifacts.review_bundle;
  }
  setNotice("视频处理计划已生成", "ok");
}

async function importVideoKnowledgeArtifacts() {
  const bundleDir = el.videoBundleDir.value || (el.videoWorkspace.value ? `${el.videoWorkspace.value.replace(/[\\/]+$/, "")}/webui-bundle` : "");
  const data = await postJSON("/api/import-video-knowledge-artifacts", {
    bundle_dir: bundleDir,
    title: el.videoTitle.value,
    claim_id: el.videoImportClaimSelect.value,
    source_quality: "unknown",
  });
  if (data.state) renderProject(data.state);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderVideoKnowledgeBridge(data.result, "imported");
  setNotice("视频知识包已作为候选材料导入", "ok");
}

async function checkVideoRunArtifacts() {
  const bundleDir = el.videoBundleDir.value || (el.videoWorkspace.value ? `${el.videoWorkspace.value.replace(/[\\/]+$/, "")}/webui-bundle` : "");
  const data = await postJSON("/api/check-video-run-artifacts", { bundle_dir: bundleDir });
  el.output.textContent = JSON.stringify(data.result, null, 2);
  renderVideoKnowledgeBridge(data.result, "artifact_status");
  setNotice(data.ok ? "视频 bundle 产物齐全。" : "视频 bundle 产物缺失，请先运行视频处理。", data.ok ? "ok" : "warn");
}

function renderVideoKnowledgeBridge(result, phase) {
  const ok = Boolean(result?.ok);
  const command = Array.isArray(result?.command) ? result.command.join(" ") : "";
  const artifacts = result?.expected_artifacts || {};
  const importedArtifacts = result?.artifacts || {};
  el.videoBridgeSummary.innerHTML = `
    <span class="pill ${ok ? "ok" : phase === "planned" ? "bad" : "bad"}">${safe(phase === "planned" ? "计划" : ok ? "完成" : "失败")}</span>
    <strong>${safe(result?.tool || "video-knowledge-pipeline")}</strong>
    <small>${safe(result?.media_path || result?.source?.title || result?.failure_next_action || "等待视频处理计划")}</small>
  `;
  const rows = [];
  if (result?.media_path) rows.push(["Video", result.media_path]);
  if (result?.workspace) rows.push(["Workspace", result.workspace]);
  if (command) rows.push(["Command", command]);
  if (artifacts.review_html) rows.push(["Review", artifacts.review_html]);
  if (artifacts.knowledge_note) rows.push(["Knowledge", artifacts.knowledge_note]);
  if (artifacts.full_transcript) rows.push(["Transcript", artifacts.full_transcript]);
  if (result?.source?.id) rows.push(["Source", `${result.source.id} · ${result.source.title}`]);
  if (result?.evidence?.id) rows.push(["Evidence", `${result.evidence.id} · candidate`]);
  if (importedArtifacts.review_html?.path) rows.push(["Review", importedArtifacts.review_html.path]);
  if (result?.manifest_path) rows.push(["Manifest", result.manifest_path]);
  if (result?.delegation_boundary) rows.push(["Boundary", result.delegation_boundary]);
  if (result?.failure_next_action) rows.push(["Next", result.failure_next_action]);
  el.videoBridgeResultRows.innerHTML = rows.length ? rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("") : `<div class="empty-state">暂无视频桥接结果。</div>`;
}

function renderLocalToolAction(result) {
  const rows = [
    ["Tool", result?.tool_id || ""],
    ["Action", result?.action || ""],
    ["Dry run", result?.dry_run ? "yes" : "no"],
    ["Executed", result?.executed ? "yes" : "no"],
    ["Command", result?.command || ""],
    ["Boundary", result?.boundary || ""],
  ];
  el.localToolActionRows.innerHTML = rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
}

function researchLoopPayload(extra = {}) {
  return {
    query: el.researchGapQuery.value.trim() || el.question.value.trim() || "",
    mode: "academic",
    rounds: Number(el.researchLoopRounds.value || 3),
    max_results: Number(el.researchLoopMaxResults.value || 8),
    max_queries_per_round: Number(el.researchGapMaxQueries.value || 3),
    fetch: true,
    no_network: false,
    timeout_seconds: 240,
    status_timeout_seconds: 5,
    ...extra,
  };
}

async function analyzeResearchGaps() {
  const data = await postJSON("/api/analyze-research-gaps", {
    query: el.researchGapQuery.value.trim() || el.question.value.trim() || "",
    max_queries_per_round: Number(el.researchGapMaxQueries.value || 3),
  });
  if (data.state) renderProject(data.state);
  renderResearchGapLoop(data.result, "gap_analysis");
  el.output.textContent = JSON.stringify(data.result, null, 2);
  setNotice(data.result?.actionable_queries?.length ? "发现可继续搜索的研究缺口。" : "没有 actionable search gap；请优先处理审核队列。", data.result?.actionable_queries?.length ? "warn" : "ok");
}

async function runResearchLoop() {
  const mode = state.bridgeStatus?.backend_mode || "";
  if (mode && mode !== "full_research") {
    throw new Error(`当前 backend mode 是 ${mode}，不能 live 执行 research loop。请先恢复 ai-research-workflow/SearXNG，或只读取已有 artifact。`);
  }
  const data = await postJSON("/api/research-loop", researchLoopPayload());
  if (data.state) renderProject(data.state);
  renderResearchGapLoop(data.result, "loop_run");
  renderResearchLoopList(data.loops);
  el.output.textContent = JSON.stringify(data.result, null, 2);
  await loadToolBridgeStatus().catch(() => null);
  setNotice("Research loop 已完成；产物是 candidate-only，需要人工审核。", data.ok ? "ok" : "warn");
}

async function loadResearchLoops() {
  const data = await getJSON(`/api/research-loops?root=${encodeURIComponent(el.root.value)}&limit=20`);
  renderResearchLoopList(data);
  el.output.textContent = JSON.stringify(data, null, 2);
  setNotice(`已读取 ${data.count || 0} 个 research loop。`, "ok");
  return data;
}

async function readResearchLoop() {
  const query = new URLSearchParams({ root: el.root.value, id: el.researchLoopId.value.trim() });
  const data = await getJSON(`/api/research-loop?${query.toString()}`);
  renderResearchGapLoop(data, "loop_read");
  el.output.textContent = JSON.stringify(data, null, 2);
  setNotice(data.ok ? "Research loop 已读取。" : "没有找到 research loop。", data.ok ? "ok" : "warn");
}

async function exportResearchLoopPack() {
  const data = await postJSON("/api/export-research-loop-review-pack", { id: el.researchLoopId.value.trim() });
  if (data.state) renderProject(data.state);
  renderResearchGapLoop(data.result, "loop_export");
  renderResearchLoopList(data.loops);
  el.output.textContent = renderResearchLoopPackMarkdown(data.result);
  setNotice(data.ok ? "Research loop 审核包已导出。" : "Research loop 审核包导出失败。", data.ok ? "ok" : "warn");
}

function renderResearchGapLoop(result, phase = "gap_analysis") {
  const ok = Boolean(result?.ok);
  const actionable = result?.actionable_queries || [];
  const gaps = result?.gaps || [];
  const imported = result?.imported_counts || {};
  const status = result?.status || (phase === "gap_analysis" ? result?.status || "analyzed" : "unknown");
  const className = ok && status !== "blocked_bridge_down" ? (actionable.length ? "warn" : "ok") : "bad";
  el.researchLoopSummary.className = `backend-mode-banner ${className}`;
  el.researchLoopSummary.innerHTML = `
    <span class="pill ${className === "ok" ? "ok" : className === "bad" ? "bad" : ""}">${safe(status)}</span>
    <strong>${safe(result?.query || "Research loop")}</strong>
    <small>${safe(result?.stop_reason || `${actionable.length} actionable queries · ${gaps.length} gaps · candidate-only`)}</small>
  `;
  const rows = [
    ["Phase", phase],
    ["Backend", result?.backend_mode || state.bridgeStatus?.backend_mode || ""],
    ["Rounds", result?.round_count ?? (result?.rounds || []).length ?? ""],
    ["Actionable", String(actionable.length)],
    ["Gaps", String(gaps.length)],
    ["Imported", `sources ${imported.sources || 0}, claims ${imported.claims || 0}, evidence ${imported.evidence || 0}`],
    ["Candidate", result?.candidate_only === false ? "no" : "yes"],
    ["Review", result?.human_review_required === false ? "not required" : "required"],
  ];
  if (result?.artifact_dir) rows.push(["Artifacts", result.artifact_dir]);
  if (result?.output_dir) rows.push(["Review pack", result.output_dir]);
  if (result?.error) rows.push(["Error", result.error]);
  actionable.slice(0, 4).forEach((item, index) => rows.push([`Query ${index + 1}`, item.query || ""]));
  el.researchLoopResultRows.innerHTML = rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
}

function renderResearchLoopList(payload) {
  const loops = payload?.loops || [];
  if (!loops.length) {
    el.researchLoopResultRows.innerHTML = `<div class="empty-state">暂无 research loop 记录。</div>`;
    return;
  }
  el.researchLoopResultRows.innerHTML = loops.slice(0, 10).map((item) => `
    <div class="bridge-result-row">
      <span>${safe(item.status || "unknown")}</span>
      <strong>${safe(item.id || item.artifact_dir || "")}</strong>
      <small>${safe(item.stop_reason || item.query || "")}</small>
    </div>
  `).join("");
  const latest = loops[0];
  if (latest && !el.researchLoopId.value.trim()) {
    el.researchLoopId.value = latest.id || "";
  }
}

function renderResearchLoopPackMarkdown(result) {
  const files = result?.files || {};
  const lines = [
    "# Research loop 审核包",
    "",
    `Candidate only: ${result?.candidate_only === false ? "no" : "yes"}`,
    `Human review required: ${result?.human_review_required === false ? "no" : "yes"}`,
    `Output: ${result?.output_dir || ""}`,
    "",
    "## Files",
  ];
  Object.entries(files).forEach(([key, value]) => lines.push(`- ${key}: ${value}`));
  lines.push("", "## Boundary", "", result?.boundary || "Review pack only.");
  return lines.join("\n");
}

function renderBridgeAction(result) {
  const rows = [
    ["Action", result?.action || ""],
    ["Status", result?.status || ""],
    ["Dry run", result?.dry_run ? "yes" : "no"],
    ["Executed", result?.executed ? "yes" : "no"],
    ["Bridge run", result?.bridge_run_id || result?.bridge_run_path || ""],
    ["Artifacts", (result?.artifact_paths || []).slice(0, 3).join("；")],
    ["Imported", JSON.stringify(result?.imported_counts || {})],
    ["Recovery", result?.error || result?.recovery_hint || ""],
  ];
  el.bridgeActionResultRows.innerHTML = rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
}

function renderToolBridgeStatus(status) {
  const tools = status?.tools || [];
  const runs = status?.recent_runs || [];
  const inboxCounts = status?.source_inbox?.counts || {};
  const reviewQueue = status?.review_queue || {};
  const actions = status?.next_actions || [];
  renderBackendMode(status);
  const rows = [
    ["Mode", `${status?.backend_mode_label || status?.backend_mode || "unknown"} · ${status?.backend_summary || ""}`],
    ["Fallback", (status?.fallback_scope || []).join("；")],
    ["Inbox", `candidate ${inboxCounts.candidate || 0}, imported ${inboxCounts.imported || 0}, rejected ${inboxCounts.rejected || 0}`],
    ["Review", `${reviewQueue.count || 0} item(s)`],
    ["Runs", `${runs.length} recent run(s)`],
  ];
  tools.forEach((tool) => {
    const last = tool.last_run || {};
    rows.push([
      tool.name,
      `${tool.available ? "available" : "missing"} · runs ${tool.recent_run_count || 0}${tool.last_error ? ` · ${tool.last_error}` : last.kind ? ` · ${last.kind}` : ""}`,
    ]);
  });
  actions.slice(0, 4).forEach((action, index) => rows.push([`Next ${index + 1}`, action]));
  el.toolBridgeStatusRows.innerHTML = rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
  if (status?.bridge_runs) {
    renderBridgeRuns(status.bridge_runs);
  }
}

function renderBackendMode(status) {
  if (!el.backendModeBanner) return;
  const mode = status?.backend_mode || "unknown";
  const label = status?.backend_mode_label || mode;
  const className = mode === "full_research" ? "ok" : mode === "blocked" ? "bad" : "warn";
  if (el.researchLoopRun) {
    el.researchLoopRun.disabled = mode !== "full_research";
    el.researchLoopRun.title = mode === "full_research" ? "显式 live 执行 research loop" : "backend 不是 full_research，只能查看计划和已有 artifact";
  }
  el.backendModeBanner.className = `backend-mode-banner ${className}`;
  el.backendModeBanner.innerHTML = `
    <span class="pill ${className}">${safe(mode)}</span>
    <strong>${safe(label)}</strong>
    <small>${safe(status?.backend_summary || "等待桥接状态刷新。")}</small>
  `;
}

function renderSyncSafety(audit) {
  const counts = audit?.counts || {};
  const origin = audit?.github_origin_advice || {};
  const protectedRows = audit?.protected_material || [];
  const unknownRows = audit?.needs_manual_classification || [];
  const rows = [
    ["Dirty", audit?.dirty ? "yes" : "no"],
    ["Branch", audit?.branch || ""],
    ["Origin", origin.origin_present ? "present" : "missing"],
    ["Counts", `source ${counts.source_candidates || 0}, protected ${counts.protected || 0}, unknown ${counts.needs_manual_classification || 0}`],
    ["GitHub", `${origin.recommended_repo_name || ""} · ${origin.recommended_visibility || ""}`],
  ];
  (audit?.next_actions || []).slice(0, 3).forEach((item, index) => rows.push([`Next ${index + 1}`, item]));
  protectedRows.slice(0, 4).forEach((item) => rows.push(["Protected", `${item.path} · ${item.reason}`]));
  unknownRows.slice(0, 3).forEach((item) => rows.push(["Inspect", `${item.path} · ${item.reason}`]));
  el.syncSafetyRows.innerHTML = rows.map(([label, value]) => `
    <div class="bridge-result-row"><span>${safe(label)}</span><strong>${safe(value)}</strong></div>
  `).join("");
}

function renderBridgeRuns(payload) {
  const runs = payload?.runs || [];
  const rows = runs.slice(0, 12).map((run) => {
    const id = run.id || run.path || "";
    const artifacts = (run.artifact_paths || []).slice(0, 2).join("；");
    return `
      <div class="bridge-result-row">
        <span>${safe(run.status || "unknown")} · ${safe(run.tool || "")}</span>
        <strong>${safe(run.action || run.kind || "")}</strong>
        <small>${safe(run.error || run.recovery_hint || artifacts || id)}</small>
      </div>
    `;
  }).join("");
  const counts = payload?.counts || {};
  el.toolBridgeStatusRows.innerHTML = `
    <div class="bridge-result-row"><span>Bridge runs</span><strong>${safe(counts.total || runs.length)} total · failed ${safe(counts.failed || 0)} · imported ${safe(counts.imported || 0)}</strong></div>
    ${rows || `<div class="empty-state">暂无 bridge run。</div>`}
  `;
}

function renderCompletenessAudit(audit) {
  const items = audit?.items || [];
  const coverage = audit?.coverage || {};
  const metricRows = [
    ["Ready", audit?.ready_for_answer ? "yes" : "no"],
    ["Blockers", `${(audit?.blocking_gates || []).length}`],
    ["Claims", `${coverage.claims_with_verified_evidence || 0}/${coverage.claim_count || 0} verified`],
    ["Counter/context", `${coverage.claims_with_counter_or_context || 0}/${coverage.claim_count || 0}`],
    ["Candidate evidence", `${coverage.candidate_evidence || 0}`],
  ].map(([label, value]) => `
    <div class="overview-row">
      <span class="pill">${safe(label)}</span>
      <div><strong>${safe(value)}</strong></div>
    </div>
  `).join("");
  const itemRows = items.slice(0, 8).map((item) => `
    <div class="overview-row ${item.severity === "blocker" ? "missing" : "warning"}">
      <span class="pill ${item.severity === "blocker" ? "bad" : ""}">${safe(item.severity)}</span>
      <div>
        <strong>${safe(item.title)}</strong>
        <small>${safe(item.action)}</small>
      </div>
    </div>
  `).join("");
  el.completenessAuditRows.innerHTML = metricRows + (itemRows || `<div class="empty-state">没有发现阻塞项。</div>`);
}

function renderGraphCandidates(payload) {
  const rows = payload?.candidates || [];
  if (!rows.length) {
    el.graphCandidateRows.innerHTML = `<div class="empty-state">还没有图谱候选边。可以先生成候选边。</div>`;
    return;
  }
  el.graphCandidateRows.innerHTML = rows.slice(0, 40).map((edge) => `
    <div class="review-item" data-graph-row data-from-id="${safe(edge.from_id)}" data-to-id="${safe(edge.to_id)}">
      <span class="pill ${edge.status === "accepted" || edge.status === "verified" ? "ok" : edge.status === "rejected" ? "bad" : ""}">${safe(edge.status || "candidate")}</span>
      <div>
        <strong>${safe(edge.edge_type)} · ${safe(edge.from_id)} -> ${safe(edge.to_id)}</strong>
        <small>${safe(edge.reason || "")}</small>
        <small>evidence: ${safe(edge.evidence_ref || "")} · created_by: ${safe(edge.created_by || "")}</small>
        <input data-graph-note placeholder="审核备注" />
      </div>
      <div class="row-actions">
        <button class="mini-btn" type="button" data-graph-review="accepted">接受</button>
        <button class="mini-btn" type="button" data-graph-review="rejected">拒绝</button>
      </div>
    </div>
  `).join("");
}

function renderLocalToolActionMarkdown(result) {
  return [
    "# 本地工具动作预览",
    "",
    `Tool: ${result?.tool_id || ""}`,
    `Action: ${result?.action || ""}`,
    `Dry run: ${result?.dry_run ? "yes" : "no"}`,
    `Executed: ${result?.executed ? "yes" : "no"}`,
    "",
    "## Command",
    "",
    "```powershell",
    result?.command || "",
    "```",
    "",
    "## Boundary",
    "",
    result?.boundary || "",
  ].join("\n");
}

el.addClaim.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/claim", { text: el.claimText.value, notes: el.claimNotes.value });
    renderProject(data.state);
    setNotice("主张已添加", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.addEvidence.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/evidence", {
      claim_id: el.evidenceClaim.value,
      source_id: el.evidenceSource.value,
      relation: el.evidenceRelation.value,
      confidence: el.evidenceConfidence.value,
      quote_or_note: el.evidenceQuote.value,
    });
    renderProject(data.state);
    setNotice("证据已添加", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.refreshTools.addEventListener("click", () => loadTools().catch((error) => setNotice(error.message, "error")));
el.videoPlan.addEventListener("click", () => planVideoKnowledgeRun().catch((error) => setNotice(error.message, "error")));
el.videoArtifactCheck.addEventListener("click", () => checkVideoRunArtifacts().catch((error) => setNotice(error.message, "error")));
el.videoImport.addEventListener("click", () => importVideoKnowledgeArtifacts().catch((error) => setNotice(error.message, "error")));
el.videoHealth.addEventListener("click", async () => {
  const data = await postJSON("/api/video-knowledge", { args: ["asr-env-status"], timeout_seconds: 120 });
  el.output.textContent = JSON.stringify(data, null, 2);
  renderVideoKnowledgeBridge(data.result || data, "status");
});
el.runVideoTool.addEventListener("click", async () => {
  try {
    const args = el.videoArgs.value.split(" ").filter(Boolean);
    const data = await postJSON("/api/video-knowledge", { args, timeout_seconds: 120 });
    el.output.textContent = JSON.stringify(data, null, 2);
    renderVideoKnowledgeBridge(data.result || data, "executed");
    setNotice("视频工具调用完成", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.localToolDryRun.addEventListener("click", async () => {
  try {
    const args = JSON.parse(el.localToolArgs.value || "{}");
    const data = await postJSON("/api/local-tool-action", {
      tool_id: el.localToolId.value,
      action: el.localToolAction.value,
      args,
      execute: false,
    });
    renderLocalToolAction(data.result);
    el.output.textContent = renderLocalToolActionMarkdown(data.result);
    setNotice("工具动作已预览。默认 dry-run，未执行外部工具。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.researchGapAnalyze.addEventListener("click", () => analyzeResearchGaps().catch((error) => setNotice(error.message, "error")));
el.researchLoopRun.addEventListener("click", () => runResearchLoop().catch((error) => setNotice(error.message, "error")));
el.researchLoopList.addEventListener("click", () => loadResearchLoops().catch((error) => setNotice(error.message, "error")));
el.researchLoopRead.addEventListener("click", () => readResearchLoop().catch((error) => setNotice(error.message, "error")));
el.researchLoopExport.addEventListener("click", () => exportResearchLoopPack().catch((error) => setNotice(error.message, "error")));
el.bridgeActionPlan.addEventListener("click", async () => {
  try {
    const args = JSON.parse(el.bridgeActionArgs.value || "{}");
    const data = await postJSON("/api/plan-bridge-action", {
      action: el.bridgeActionName.value,
      args,
    });
    renderBridgeAction(data.result);
    el.output.textContent = JSON.stringify(data.result, null, 2);
    setNotice("Bridge action 已预览：只写 planned run，未执行外部工具。", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.bridgeActionRun.addEventListener("click", async () => {
  try {
    const args = JSON.parse(el.bridgeActionArgs.value || "{}");
    const data = await postJSON("/api/run-bridge-action", {
      action: el.bridgeActionName.value,
      args,
      execute: true,
      timeout_seconds: 120,
    });
    renderBridgeAction(data.result);
    if (data.state) renderProject(data.state);
    await loadToolBridgeStatus().catch(() => null);
    el.output.textContent = JSON.stringify(data.result, null, 2);
    setNotice("Bridge action live 执行完成；导入内容仍需人工审核。", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.enqueueBridgeActions.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/enqueue-bridge-actions", {});
    if (data.state) renderProject(data.state);
    renderWorkQueue(data.work_queue || data.result);
    el.output.textContent = renderWorkQueueMarkdown(data.work_queue || data.result);
    setNotice(`已入队 ${data.result?.added_count || 0} 个明确 bridge action。默认 dry-run。`, "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.refreshToolBridgeStatus.addEventListener("click", () => loadToolBridgeStatus().then(() => setNotice("工具桥接状态已刷新。", "ok")).catch((error) => setNotice(error.message, "error")));
el.syncSafety.addEventListener("click", async () => {
  try {
    const data = await getJSON(`/api/sync-safety?repo=${encodeURIComponent(".")}`);
    renderSyncSafety(data);
    el.output.textContent = JSON.stringify(data, null, 2);
    const counts = data.counts || {};
    setNotice(`同步安全已检查：protected ${counts.protected || 0}, unknown ${counts.needs_manual_classification || 0}。`, data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.readBridgeRun.addEventListener("click", async () => {
  try {
    const id = el.bridgeRunId.value.trim();
    const data = await getJSON(`/api/bridge-run?root=${encodeURIComponent(el.root.value)}&id=${encodeURIComponent(id)}`);
    el.output.textContent = JSON.stringify(data, null, 2);
    setNotice("Bridge run 已读取。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.retryBridgeRun.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/retry-bridge-run-plan", { id: el.bridgeRunId.value.trim() });
    el.output.textContent = JSON.stringify(data.result, null, 2);
    setNotice("已生成只读重试计划。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.refreshGraphCandidates.addEventListener("click", () => loadGraphCandidates().then(() => setNotice("图谱候选已刷新。", "ok")).catch((error) => setNotice(error.message, "error")));
el.generateGraphCandidates.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/generate-graph-candidates", {});
    renderGraphCandidates(data.graph);
    if (data.state) renderProject(data.state);
    el.output.textContent = JSON.stringify(data.result, null, 2);
    setNotice(`已生成 ${data.result?.added_count || 0} 条新候选边。`, "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.exportReviewedGraph.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/export-reviewed-graph", {});
    renderGraphCandidates(data.graph);
    el.output.textContent = JSON.stringify(data.result, null, 2);
    setNotice("已导出人工接受的图谱边。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.completenessAudit.addEventListener("click", () => loadCompletenessAudit().then((audit) => {
  el.output.textContent = JSON.stringify(audit, null, 2);
  setNotice(audit.ready_for_answer ? "完整性检查通过。发布前仍建议人工复核研究包。" : "完整性检查发现阻塞项。", audit.ready_for_answer ? "ok" : "warn");
}).catch((error) => setNotice(error.message, "error")));
el.overview.addEventListener("click", async () => {
  const data = await getJSON(`/api/overview?root=${encodeURIComponent(el.root.value)}`);
  el.output.textContent = data.markdown;
});
el.draft.addEventListener("click", async () => {
  const data = await getJSON(`/api/draft?include_candidate=1&root=${encodeURIComponent(el.root.value)}`);
  el.output.textContent = data.markdown;
});
el.exportFinalAnswer.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/export-final-answer", { allow_incomplete: false });
    if (data.state) renderProject(data.state);
    el.output.textContent = renderFinalAnswerResult(data.result);
    setNotice("最终答案已导出。", "ok");
  } catch (error) {
    const audit = await loadCompletenessAudit().catch(() => null);
    el.output.textContent = renderFinalAnswerResult({
      ok: false,
      blocking_gates: audit?.blocking_gates || [],
      next_actions: audit?.next_actions || [error.message],
    });
    setNotice("完整性审计未通过，最终答案导出被阻塞。", "warn");
  }
});
el.exportResearchPack.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/export-research-pack", {});
    if (data.state) renderProject(data.state);
    el.output.textContent = renderResearchPackResult(data.result);
    setNotice("研究包已导出，请人工审核后再发布或写回知识库。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.exportObsidianPack.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/export-research-pack-obsidian", {
      vault: el.obsidianVault.value,
      folder: el.obsidianFolder.value,
    });
    if (data.state) renderProject(data.state);
    el.output.textContent = renderKnowledgeBaseHandoffResult("Obsidian 审核包已导出", data.result);
    setNotice("Obsidian 审核包已导出。它只是 Markdown 审核材料，不会自动发布结论。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.logseqHandoff.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/create-logseq-review-handoff", {});
    if (data.state) renderProject(data.state);
    el.output.textContent = renderKnowledgeBaseHandoffResult("Logseq 审核包已生成", data.result);
    setNotice("Logseq 审核包已生成。没有调用 Logseq 写 API。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.agentRunbook.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/agent-runbook", {});
    if (data.state) renderProject(data.state);
    el.output.textContent = data.result?.markdown || JSON.stringify(data.result, null, 2);
    setNotice("Agent 下一步 Runbook 已生成。人工审核项不会被自动执行。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.agentManifest.addEventListener("click", async () => {
  try {
    const data = await getJSON(`/api/agent/manifest?root=${encodeURIComponent(el.root.value)}`);
    el.output.textContent = JSON.stringify(data, null, 2);
    setNotice("Agent manifest 已读取。它描述 UI/CLI/MCP/API 对齐和人工审核边界。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.cockpitReadiness.addEventListener("click", async () => {
  try {
    const data = await getJSON(`/api/cockpit-readiness?root=${encodeURIComponent(el.root.value)}`);
    el.output.textContent = JSON.stringify(data, null, 2);
    setNotice(data.ok ? "驾驶舱核心能力检查通过。" : "驾驶舱能力仍有缺口。", data.ok ? "ok" : "warn");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.enqueueRunbookTasks.addEventListener("click", async () => {
  try {
    const data = await postJSON("/api/enqueue-runbook-tasks", {});
    if (data.state) renderProject(data.state);
    renderWorkQueue(data.result);
    el.output.textContent = renderWorkQueueMarkdown(data.result);
    setNotice("Runbook 已转成工作队列。人工项仍然需要人工处理。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});
el.refreshWorkQueue.addEventListener("click", async () => {
  try {
    const data = await getJSON(`/api/work-queue?root=${encodeURIComponent(el.root.value)}`);
    renderWorkQueue(data);
    el.output.textContent = renderWorkQueueMarkdown(data);
    setNotice("工作队列已刷新。", "ok");
  } catch (error) {
    setNotice(error.message, "error");
  }
});

function renderResearchPackResult(result) {
  const files = result?.files || {};
  const lines = [
    `# 研究包导出完成`,
    ``,
    `Human review required: ${result?.human_review_required ? "yes" : "unknown"}`,
    `Output: ${result?.output_dir || ""}`,
    ``,
    `## Files`,
  ];
  Object.entries(files).forEach(([key, value]) => {
    lines.push(`- ${key}: ${value}`);
  });
  lines.push(``, `## Next actions`);
  (result?.next_actions || []).forEach((item, index) => {
    lines.push(`${index + 1}. ${item}`);
  });
  return lines.join("\n");
}

function renderFinalAnswerResult(result) {
  if (!result?.ok) {
    const blockers = (result?.blocking_gates || []).map((item) => `- ${item}`).join("\n") || "- unknown";
    const actions = (result?.next_actions || []).map((item) => `- ${item}`).join("\n") || "- 先运行完整性审计。";
    return [
      "# 最终答案被阻塞",
      "",
      "当前研究还没有通过完整性审计，不能导出最终答案。",
      "",
      "## Blocking Gates",
      "",
      blockers,
      "",
      "## Next Actions",
      "",
      actions,
    ].join("\n");
  }
  return [
    "# 最终答案已导出",
    "",
    `Ready: ${result.ready_for_answer ? "yes" : "no"}`,
    `Incomplete export: ${result.allow_incomplete ? "yes" : "no"}`,
    "",
    "## Files",
    "",
    `- Markdown: ${result.files?.markdown || ""}`,
    `- Audit: ${result.files?.audit || ""}`,
    `- JSON: ${result.files?.json || ""}`,
  ].join("\n");
}

function renderKnowledgeBaseHandoffResult(title, result) {
  const files = result?.files || {};
  const lines = [
    `# ${title}`,
    ``,
    `Human review required: ${result?.human_review_required ? "yes" : "unknown"}`,
    `Direct write: ${result?.direct_write ? "yes" : "no"}`,
    `Output: ${result?.output_dir || result?.path || ""}`,
    ``,
    `## Boundary`,
    ``,
    result?.boundary || "Review package only.",
  ];
  if (Object.keys(files).length) {
    lines.push(``, `## Files`);
    Object.entries(files).forEach(([key, value]) => {
      lines.push(`- ${key}: ${value}`);
    });
  }
  if (result?.path) {
    lines.push(``, `## Handoff`, `- ${result.path}`);
  }
  return lines.join("\n");
}

function renderWorkQueue(queue) {
  const tasks = queue?.tasks || [];
  if (!tasks.length) {
    el.workQueuePanel.innerHTML = `<div class="bridge-row"><span class="pill">empty</span><strong>工作队列为空</strong><small>可以先生成 Agent Runbook 再入队。</small></div>`;
    return;
  }
  el.workQueuePanel.innerHTML = tasks.slice(0, 12).map((task) => `
    <div class="bridge-row">
      <span class="pill">${safe(task.status || "pending")}</span>
      <strong>${safe(task.title || task.kind || "Task")}</strong>
      <small>${safe(task.note || task.human_boundary || task.command || "")}</small>
      ${task.bridge_run_id ? `<small>bridge run: ${safe(task.bridge_run_id)}</small>` : ""}
      <div class="row-actions">
        <button class="mini-btn" type="button" data-workqueue-preview="${safe(task.id)}">dry-run 预览</button>
        ${task.tool_action && task.status !== "needs_human" ? `<button class="mini-btn danger-lite" type="button" data-workqueue-execute="${safe(task.id)}">live 执行</button>` : ""}
      </div>
    </div>
  `).join("");
}

function renderWorkQueueMarkdown(queue) {
  const counts = queue?.counts || {};
  const lines = [
    "# 工作队列",
    "",
    `Total: ${counts.total || 0}`,
    `Pending: ${counts.pending || 0}`,
    `Needs human: ${counts.needs_human || 0}`,
    "",
    "## Tasks",
  ];
  (queue?.tasks || []).forEach((task) => {
    lines.push(`- \`${task.status}\` ${task.title || task.kind}: ${task.command || task.human_boundary || ""}`);
  });
  return lines.join("\n");
}

Promise.all([loadProject(), loadTools()]).catch((error) => setNotice(error.message, "error"));
