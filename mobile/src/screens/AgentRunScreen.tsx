import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, AppState, BackHandler, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View, type ScrollViewInstance } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { mobileApi } from "../api";
import { StatusPill } from "../components/StatusPill";
import { colors } from "../theme";
import type { AgentEvent, AgentProgress, Job } from "../types";
import { formatDate, getFeedbackDecisionSequence, humanize, isActive, renderValue, relativeTime, workflowIcons, workflowLabels } from "../utils";

export function AgentRunScreen({ apiUrl, initialJob, onBack }: { apiUrl: string; initialJob: Job; onBack: () => void }) {
  const [job, setJob] = useState(initialJob);
  const [progress, setProgress] = useState<AgentProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const scrollRef = useRef<ScrollViewInstance>(null);

  const load = useCallback(async () => {
    try {
      const [latestJob, latestProgress] = await Promise.all([
        mobileApi.job(apiUrl, initialJob.id),
        mobileApi.progress(apiUrl, initialJob.id),
      ]);
      setJob(latestJob);
      setProgress(latestProgress);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to load agent history.");
    }
  }, [apiUrl, initialJob.id]);

  useEffect(() => {
    load();
    const timer = setInterval(() => { if (AppState.currentState === "active") load(); }, isActive(job.status) ? 2_000 : 5_000);
    return () => clearInterval(timer);
  }, [job.status, load]);

  useEffect(() => {
    if (Platform.OS !== "android") return;
    const subscription = BackHandler.addEventListener("hardwareBackPress", () => {
      onBack();
      return true;
    });
    return () => subscription.remove();
  }, [onBack]);

  useEffect(() => {
    if (progress?.events.length) requestAnimationFrame(() => scrollRef.current?.scrollToEnd({ animated: false }));
  }, [progress?.events.length]);

  const send = async () => {
    const trimmed = message.trim();
    if (!trimmed || job.status !== "review_required" || sending) return;
    setSending(true);
    try {
      const updated = await mobileApi.sendFeedback(apiUrl, job.id, trimmed);
      setJob(updated);
      setMessage("");
      await load();
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "Unable to send guidance.");
    } finally {
      setSending(false);
    }
  };

  const retry = async () => {
    setRetrying(true);
    try {
      setJob(await mobileApi.retry(apiUrl, job.id));
      setError(null);
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "Unable to retry the run.");
    } finally {
      setRetrying(false);
    }
  };

  const canMessage = job.status === "review_required";
  const canSend = canMessage && message.trim().length > 0 && !sending;
  const feedbackSequence = getFeedbackDecisionSequence(job.result, job.warnings, progress?.events ?? []);
  const decisionsByEvent = new Map(feedbackSequence.entries.map((entry) => [entry.eventIndex, entry.decisions]));

  return (
    <SafeAreaView style={styles.safe} edges={["top", "bottom", "left", "right"]}>
      <KeyboardAvoidingView style={styles.safe} behavior={Platform.OS === "ios" ? "padding" : undefined}>
        <View style={styles.header}>
          <Pressable accessibilityLabel="Back to agent inbox" onPress={onBack} style={({ pressed }) => [styles.headerButton, pressed && styles.pressed]}><MaterialCommunityIcons name="arrow-left" size={21} color={colors.zinc200} /></Pressable>
          <View style={styles.agentMark}>
            <MaterialCommunityIcons name={workflowIcons[job.workflow]} size={20} color={colors.white} />
            {isActive(job.status) && <View style={styles.liveDot} />}
          </View>
          <View style={styles.headerBody}>
            <Text numberOfLines={1} style={styles.headerTitle}>{job.title}</Text>
            <Text numberOfLines={1} style={styles.headerSubtitle}>{workflowLabels[job.workflow]} · {progress?.stage ? humanize(progress.stage) : "Loading trace"}</Text>
          </View>
          <StatusPill status={job.status} compact />
        </View>

        <ScrollView ref={scrollRef} style={styles.scroll} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          <RunSummary job={job} progress={progress} />
          {error && <Pressable onPress={load} style={styles.errorBanner}><MaterialCommunityIcons name="alert-circle-outline" size={18} color={colors.rose300} /><Text style={styles.errorText}>{error} Tap to retry.</Text></Pressable>}
          {!progress && !error ? <View style={styles.loading}><ActivityIndicator color={colors.violet400} /><Text style={styles.loadingText}>Loading agent history…</Text></View>
            : progress?.events.length ? <View style={styles.timeline}>{progress.events.map((event, index) => <View key={`${event.turn}-${event.type}-${index}`}><EventBubble event={event} />{(event.actor === "user" || event.type === "user_feedback") && <FeedbackDecisionCard decisions={decisionsByEvent.get(index) ?? []} />}</View>)}{feedbackSequence.unmatched.length > 0 && <FeedbackDecisionCard decisions={feedbackSequence.unmatched} title="Other current constraints" />}</View>
            : progress ? <EmptyTrace /> : null}

          {job.status === "failed" && (
            <View style={styles.failedCard}>
              <Text style={styles.failedTitle}>This run stopped</Text>
              <Text style={styles.failedBody}>{job.error ?? "The agent could not complete this run."}</Text>
              <Pressable disabled={retrying} onPress={retry} style={({ pressed }) => [styles.retryButton, pressed && styles.pressed, retrying && styles.disabled]}>
                {retrying ? <ActivityIndicator size="small" color={colors.background} /> : <MaterialCommunityIcons name="refresh" size={17} color={colors.background} />}
                <Text style={styles.retryText}>Retry run</Text>
              </Pressable>
            </View>
          )}

          {job.artifacts.length > 0 && (
            <View style={styles.artifacts}>
              <Text style={styles.sectionLabel}>Artifacts</Text>
              {job.artifacts.map((artifact) => (
                <Pressable key={artifact.id} onPress={() => Linking.openURL(mobileApi.artifactUrl(apiUrl, artifact.download_url))} style={({ pressed }) => [styles.artifactRow, pressed && styles.pressed]}>
                  <MaterialCommunityIcons name="file-download-outline" size={19} color={colors.violet200} />
                  <Text numberOfLines={1} style={styles.artifactName}>{artifact.name}</Text>
                  <MaterialCommunityIcons name="open-in-new" size={16} color={colors.zinc600} />
                </Pressable>
              ))}
            </View>
          )}
        </ScrollView>

        <View style={styles.composerArea}>
          <View style={[styles.composer, canMessage && styles.composerActive]}>
            <TextInput
              value={message}
              onChangeText={setMessage}
              editable={canMessage && !sending}
              multiline
              maxLength={4000}
              placeholder={composerPlaceholder(job.status)}
              placeholderTextColor={colors.zinc600}
              selectionColor={colors.violet400}
              style={styles.messageInput}
            />
            <Pressable accessibilityLabel="Send message" disabled={!canSend} onPress={send} style={({ pressed }) => [styles.sendButton, !canSend && styles.sendDisabled, pressed && canSend && styles.pressed]}>
              {sending ? <ActivityIndicator size="small" color={colors.white} /> : <MaterialCommunityIcons name="send" size={18} color={canSend ? colors.white : colors.zinc600} />}
            </Pressable>
          </View>
          <Text style={styles.composerHint}>{canMessage ? `Revises ${humanize(job.review_stage ?? "current stage")} · does not approve` : "Messaging opens when human review is required"}</Text>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function RunSummary({ job, progress }: { job: Job; progress: AgentProgress | null }) {
  const coverage = progress?.total_source_chunks ? Math.round((progress.read_source_chunks.length / progress.total_source_chunks) * 100) : null;
  return (
    <View style={styles.summaryCard}>
      <View style={styles.summaryTop}>
        <View style={styles.summaryIcon}><MaterialCommunityIcons name="creation" size={18} color={colors.violet200} /></View>
        <View style={styles.summaryText}>
          <Text style={styles.summaryTitle}>Agent run started</Text>
          <Text style={styles.summaryMeta}>{formatDate(job.created_at)} · {job.model_name ?? progress?.model ?? "Configured Meta model"}</Text>
        </View>
      </View>
      <View style={styles.metrics}>
        <Metric value={progress ? `${progress.turn}/${progress.max_turns}` : "—"} label="Turns" />
        <Metric value={progress ? `${progress.stage_index}/${progress.stage_count}` : "—"} label="Stage" />
        <Metric value={coverage == null ? "—" : `${coverage}%`} label="Sources" />
      </View>
    </View>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return <View style={styles.metric}><Text style={styles.metricValue}>{value}</Text><Text style={styles.metricLabel}>{label}</Text></View>;
}

function FeedbackDecisionCard({ decisions, title = "Recorded decision" }: { decisions: string[]; title?: string }) {
  return (
    <View accessibilityLabel={title} style={styles.decisionCard}>
      <Text style={styles.decisionTitle}>{title}</Text>
      {decisions.length ? decisions.map((item) => <View key={item} style={styles.decisionRow}><View style={styles.decisionBullet} /><Text style={styles.decisionText}>{item}</Text></View>) : <Text style={styles.decisionEmpty}>No unresolved constraint was recorded for this feedback in the current draft.</Text>}
    </View>
  );
}

function EventBubble({ event }: { event: AgentEvent }) {
  const [expanded, setExpanded] = useState(false);
  const isUser = event.actor === "user" || event.type === "user_feedback";
  const failed = event.ok === false || event.type.endsWith("rejected");
  const details = { ...(event.input_details ?? {}), ...(event.output_details ?? {}) };
  const hasDetails = Boolean(event.intent || event.error || event.evidence?.length || Object.keys(details).length);
  const summary = event.summary ?? event.output_summary ?? event.input_summary ?? "The agent completed an approved workflow action.";
  return (
    <View style={[styles.event, isUser && styles.eventUser]}>
      <View style={[styles.avatar, isUser ? styles.userAvatar : failed ? styles.failedAvatar : styles.agentAvatar]}>
        <MaterialCommunityIcons name={isUser ? "account-outline" : "robot-outline"} size={16} color={isUser ? colors.sky300 : failed ? colors.rose300 : colors.violet200} />
      </View>
      <View style={styles.bubbleColumn}>
        <View style={[styles.eventMeta, isUser && styles.eventMetaUser]}>
          <Text style={styles.eventActor}>{isUser ? "You" : event.name ? humanize(event.name) : `Agent turn ${event.turn}`}</Text>
          {event.occurred_at && <Text style={styles.eventTime}>· {relativeTime(event.occurred_at)}</Text>}
        </View>
        <Pressable disabled={!hasDetails} onPress={() => setExpanded((value) => !value)} style={[styles.bubble, isUser ? styles.userBubble : failed ? styles.failedBubble : styles.agentBubble]}>
          <Text style={styles.bubbleText}>{summary}</Text>
          {hasDetails && <View style={styles.detailsToggle}><Text style={styles.detailsToggleText}>{expanded ? "Hide details" : "View details"}</Text><MaterialCommunityIcons name={expanded ? "chevron-up" : "chevron-down"} size={15} color={colors.zinc600} /></View>}
          {expanded && (
            <View style={styles.details}>
              {event.intent && <Detail label="Purpose" value={event.intent} />}
              {Object.entries(details).map(([key, value]) => <Detail key={key} label={humanize(key)} value={renderValue(value)} />)}
              {event.evidence?.length ? <Detail label="Evidence" value={event.evidence.join(" · ")} /> : null}
              {event.error && <Detail label="Error" value={event.error} error />}
            </View>
          )}
        </Pressable>
      </View>
    </View>
  );
}

function Detail({ label, value, error = false }: { label: string; value: string; error?: boolean }) {
  return <View style={styles.detail}><Text style={styles.detailLabel}>{label}</Text><Text style={[styles.detailValue, error && styles.detailError]}>{value}</Text></View>;
}

function EmptyTrace() {
  return <View style={styles.loading}><MaterialCommunityIcons name="clock-outline" size={24} color={colors.zinc600} /><Text style={styles.loadingTitle}>Waiting for the first turn</Text><Text style={styles.loadingText}>The sanitized execution history will appear here when processing begins.</Text></View>;
}

function composerPlaceholder(status: Job["status"]) {
  if (status === "review_required") return "Tell the agent what to revise…";
  if (isActive(status)) return "Agent is working…";
  if (status === "succeeded") return "This run is complete";
  return "Retry the run to continue";
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { minHeight: 72, flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, backgroundColor: colors.surface },
  headerButton: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 13, borderWidth: 1, borderColor: colors.border },
  agentMark: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 14, backgroundColor: colors.violet500 },
  liveDot: { position: "absolute", right: -1, bottom: -1, width: 11, height: 11, borderRadius: 6, borderWidth: 2, borderColor: colors.surface, backgroundColor: colors.emerald500 },
  headerBody: { flex: 1, minWidth: 0 },
  headerTitle: { color: colors.zinc100, fontSize: 14, fontWeight: "700" },
  headerSubtitle: { marginTop: 3, color: colors.zinc600, fontSize: 9 },
  scroll: { flex: 1 },
  content: { paddingHorizontal: 16, paddingTop: 18, paddingBottom: 26 },
  summaryCard: { borderRadius: 19, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceRaised, padding: 15 },
  summaryTop: { flexDirection: "row", alignItems: "center", gap: 11 },
  summaryIcon: { width: 38, height: 38, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.violet950 },
  summaryText: { flex: 1 },
  summaryTitle: { color: colors.zinc100, fontSize: 13, fontWeight: "700" },
  summaryMeta: { marginTop: 4, color: colors.zinc600, fontSize: 9, lineHeight: 13 },
  metrics: { marginTop: 14, flexDirection: "row", borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.background, overflow: "hidden" },
  metric: { flex: 1, alignItems: "center", paddingVertical: 11, borderRightWidth: StyleSheet.hairlineWidth, borderRightColor: colors.border },
  metricValue: { color: colors.zinc200, fontSize: 13, fontWeight: "700" },
  metricLabel: { marginTop: 3, color: colors.zinc600, fontSize: 8, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  decisionCard: { marginTop: 8, marginLeft: 42, borderRadius: 13, borderWidth: 1, borderColor: `${colors.amber500}45`, backgroundColor: `${colors.amber500}12`, padding: 12 },
  decisionTitle: { color: colors.amber300, fontSize: 9, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  decisionRow: { marginTop: 8, flexDirection: "row", alignItems: "flex-start", gap: 8 },
  decisionBullet: { width: 5, height: 5, marginTop: 6, borderRadius: 3, backgroundColor: colors.amber300 },
  decisionText: { flex: 1, color: colors.zinc200, fontSize: 11, lineHeight: 17 },
  decisionEmpty: { marginTop: 6, color: colors.zinc500, fontSize: 10, lineHeight: 15 },
  errorBanner: { marginTop: 14, flexDirection: "row", alignItems: "center", gap: 9, padding: 12, borderRadius: 14, borderWidth: 1, borderColor: `${colors.rose500}38`, backgroundColor: `${colors.rose500}12` },
  errorText: { flex: 1, color: colors.rose300, fontSize: 11, lineHeight: 16 },
  loading: { minHeight: 190, alignItems: "center", justifyContent: "center", gap: 9, padding: 26 },
  loadingTitle: { color: colors.zinc300, fontSize: 14, fontWeight: "700" },
  loadingText: { color: colors.zinc600, fontSize: 11, lineHeight: 17, textAlign: "center" },
  timeline: { marginTop: 22, gap: 18 },
  event: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  eventUser: { flexDirection: "row-reverse" },
  avatar: { width: 32, height: 32, alignItems: "center", justifyContent: "center", borderRadius: 11 },
  agentAvatar: { backgroundColor: `${colors.violet500}20` },
  userAvatar: { backgroundColor: `${colors.sky500}20` },
  failedAvatar: { backgroundColor: `${colors.rose500}20` },
  bubbleColumn: { flexShrink: 1, maxWidth: "84%" },
  eventMeta: { marginBottom: 5, flexDirection: "row", alignItems: "center", gap: 4 },
  eventMetaUser: { justifyContent: "flex-end" },
  eventActor: { color: colors.zinc600, fontSize: 9, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.7 },
  eventTime: { color: colors.zinc700, fontSize: 9 },
  bubble: { borderWidth: 1, paddingHorizontal: 14, paddingVertical: 12 },
  agentBubble: { borderColor: colors.border, backgroundColor: colors.surfaceRaised, borderRadius: 17, borderTopLeftRadius: 5 },
  userBubble: { borderColor: `${colors.sky500}35`, backgroundColor: `${colors.sky500}14`, borderRadius: 17, borderTopRightRadius: 5 },
  failedBubble: { borderColor: `${colors.rose500}35`, backgroundColor: `${colors.rose500}12`, borderRadius: 17, borderTopLeftRadius: 5 },
  bubbleText: { color: colors.zinc200, fontSize: 13, lineHeight: 20 },
  detailsToggle: { marginTop: 9, paddingTop: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, flexDirection: "row", alignItems: "center", gap: 2 },
  detailsToggleText: { color: colors.zinc600, fontSize: 9, fontWeight: "700" },
  details: { marginTop: 10, gap: 9 },
  detail: { gap: 2 },
  detailLabel: { color: colors.zinc500, fontSize: 9, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.5 },
  detailValue: { color: colors.zinc400, fontSize: 10, lineHeight: 16 },
  detailError: { color: colors.rose300 },
  failedCard: { marginTop: 22, borderRadius: 17, borderWidth: 1, borderColor: `${colors.rose500}35`, backgroundColor: `${colors.rose500}12`, padding: 15 },
  failedTitle: { color: colors.rose300, fontSize: 13, fontWeight: "700" },
  failedBody: { marginTop: 5, color: colors.rose300, opacity: 0.75, fontSize: 11, lineHeight: 17 },
  retryButton: { marginTop: 12, minHeight: 38, alignSelf: "flex-start", flexDirection: "row", alignItems: "center", gap: 7, borderRadius: 12, backgroundColor: colors.rose300, paddingHorizontal: 13 },
  retryText: { color: colors.background, fontSize: 11, fontWeight: "800" },
  artifacts: { marginTop: 24, gap: 8 },
  sectionLabel: { marginBottom: 2, color: colors.zinc600, fontSize: 9, fontWeight: "800", textTransform: "uppercase", letterSpacing: 1 },
  artifactRow: { minHeight: 48, flexDirection: "row", alignItems: "center", gap: 10, borderRadius: 14, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, paddingHorizontal: 13 },
  artifactName: { flex: 1, color: colors.zinc300, fontSize: 11 },
  composerArea: { paddingHorizontal: 12, paddingTop: 10, paddingBottom: 8, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, backgroundColor: colors.surface },
  composer: { minHeight: 55, flexDirection: "row", alignItems: "flex-end", gap: 8, borderRadius: 17, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceRaised, padding: 7 },
  composerActive: { borderColor: `${colors.violet400}65` },
  messageInput: { flex: 1, maxHeight: 105, minHeight: 40, color: colors.zinc100, fontSize: 13, lineHeight: 19, paddingHorizontal: 7, paddingTop: 9, paddingBottom: 7, textAlignVertical: "top" },
  sendButton: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderRadius: 13, backgroundColor: colors.violet500 },
  sendDisabled: { backgroundColor: colors.surfaceMuted },
  composerHint: { marginTop: 6, marginLeft: 4, color: colors.zinc600, fontSize: 8, lineHeight: 11 },
  pressed: { opacity: 0.65 },
  disabled: { opacity: 0.45 },
});
