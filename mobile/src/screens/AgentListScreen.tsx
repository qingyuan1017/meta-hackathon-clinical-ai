import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, AppState, FlatList, Pressable, RefreshControl, StyleSheet, Text, TextInput, View } from "react-native";
import { mobileApi } from "../api";
import { ScreenHeader } from "../components/ScreenHeader";
import { StatusPill } from "../components/StatusPill";
import { colors } from "../theme";
import type { Job } from "../types";
import { isActive, relativeTime, workflowIcons, workflowLabels } from "../utils";

type Filter = "all" | "active" | "review";

export function AgentListScreen({ apiUrl, onOpenJob, onOpenSettings }: { apiUrl: string; onOpenJob: (job: Job) => void; onOpenSettings: () => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const result = await mobileApi.jobs(apiUrl);
      setJobs(result.items);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Unable to reach the backend.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    load();
    const timer = setInterval(() => { if (AppState.currentState === "active") load(); }, 4_000);
    return () => clearInterval(timer);
  }, [load]);

  const visibleJobs = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return jobs.filter((job) => {
      const matchesText = !needle || job.title.toLowerCase().includes(needle) || workflowLabels[job.workflow].toLowerCase().includes(needle);
      const matchesFilter = filter === "all" || (filter === "active" && isActive(job.status)) || (filter === "review" && job.status === "review_required");
      return matchesText && matchesFilter;
    });
  }, [filter, jobs, search]);

  const activeCount = jobs.filter((job) => isActive(job.status)).length;
  const reviewCount = jobs.filter((job) => job.status === "review_required").length;

  return (
    <View style={styles.screen}>
      <ScreenHeader eyebrow="Clinical AI" title="Agent inbox" actionIcon="cog-outline" actionLabel="Open settings" onAction={onOpenSettings} />
      <View style={styles.controls}>
        <View style={styles.searchBox}>
          <MaterialCommunityIcons name="magnify" size={19} color={colors.zinc600} />
          <TextInput value={search} onChangeText={setSearch} placeholder="Search runs" placeholderTextColor={colors.zinc600} selectionColor={colors.violet400} style={styles.searchInput} />
          {search.length > 0 && <Pressable accessibilityLabel="Clear search" onPress={() => setSearch("")}><MaterialCommunityIcons name="close-circle" size={18} color={colors.zinc600} /></Pressable>}
        </View>
        <View style={styles.filters}>
          <FilterButton label="All" count={jobs.length} active={filter === "all"} onPress={() => setFilter("all")} />
          <FilterButton label="Live" count={activeCount} active={filter === "active"} onPress={() => setFilter("active")} />
          <FilterButton label="Review" count={reviewCount} active={filter === "review"} onPress={() => setFilter("review")} />
        </View>
      </View>
      {error && (
        <Pressable onPress={() => load(true)} style={styles.errorBanner}>
          <MaterialCommunityIcons name="wifi-alert" size={18} color={colors.rose300} />
          <Text numberOfLines={2} style={styles.errorText}>{error} Tap to retry.</Text>
        </Pressable>
      )}
      {loading ? (
        <View style={styles.center}><ActivityIndicator color={colors.violet400} /><Text style={styles.emptyText}>Loading agent runs…</Text></View>
      ) : (
        <FlatList
          data={visibleJobs}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => <JobRow job={item} onPress={() => onOpenJob(item)} />}
          contentContainerStyle={visibleJobs.length ? styles.list : styles.emptyList}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => load(true)} tintColor={colors.violet400} colors={[colors.violet500]} />}
          ListEmptyComponent={<EmptyState hasJobs={jobs.length > 0} />}
        />
      )}
    </View>
  );
}

function FilterButton({ label, count, active, onPress }: { label: string; count: number; active: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.filter, active && styles.filterActive, pressed && styles.pressed]}>
      <Text style={[styles.filterText, active && styles.filterTextActive]}>{label}</Text>
      <Text style={[styles.filterCount, active && styles.filterTextActive]}>{count}</Text>
    </Pressable>
  );
}

function JobRow({ job, onPress }: { job: Job; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [styles.row, pressed && styles.rowPressed]}>
      <View style={styles.iconWrap}>
        <MaterialCommunityIcons name={workflowIcons[job.workflow]} size={20} color={colors.violet200} />
        {isActive(job.status) && <View style={styles.liveDot} />}
      </View>
      <View style={styles.rowBody}>
        <View style={styles.rowTitleLine}>
          <Text numberOfLines={1} style={styles.rowTitle}>{job.title}</Text>
          <Text style={styles.time}>{relativeTime(job.updated_at)}</Text>
        </View>
        <Text numberOfLines={1} style={styles.workflow}>{workflowLabels[job.workflow]}</Text>
        <View style={styles.rowFooter}>
          <StatusPill status={job.status} compact />
          {job.status === "review_required" && <Text style={styles.reply}>Reply requested</Text>}
        </View>
      </View>
      <MaterialCommunityIcons name="chevron-right" size={20} color={colors.zinc700} />
    </Pressable>
  );
}

function EmptyState({ hasJobs }: { hasJobs: boolean }) {
  return (
    <View style={styles.center}>
      <View style={styles.emptyIcon}><MaterialCommunityIcons name={hasJobs ? "filter-outline" : "robot-outline"} size={27} color={colors.zinc600} /></View>
      <Text style={styles.emptyTitle}>{hasJobs ? "No matching runs" : "No agent runs yet"}</Text>
      <Text style={styles.emptyText}>{hasJobs ? "Try another search or filter." : "Start a workflow in the web workbench. Its agent history will appear here."}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  controls: { paddingHorizontal: 16, paddingTop: 14, paddingBottom: 12, gap: 10 },
  searchBox: { height: 46, flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 14, borderRadius: 15, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceRaised },
  searchInput: { flex: 1, color: colors.zinc100, fontSize: 14, paddingVertical: 0 },
  filters: { flexDirection: "row", padding: 4, borderRadius: 13, backgroundColor: colors.surface },
  filter: { flex: 1, height: 36, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, borderRadius: 10 },
  filterActive: { backgroundColor: colors.surfaceMuted },
  filterText: { color: colors.zinc600, fontSize: 11, fontWeight: "800" },
  filterCount: { color: colors.zinc700, fontSize: 10, fontWeight: "700" },
  filterTextActive: { color: colors.zinc200 },
  errorBanner: { marginHorizontal: 16, marginBottom: 8, flexDirection: "row", alignItems: "center", gap: 10, borderRadius: 13, borderWidth: 1, borderColor: `${colors.rose500}38`, backgroundColor: `${colors.rose500}12`, paddingHorizontal: 12, paddingVertical: 10 },
  errorText: { flex: 1, color: colors.rose300, fontSize: 11, lineHeight: 16 },
  list: { paddingHorizontal: 12, paddingTop: 4, paddingBottom: 24 },
  emptyList: { flexGrow: 1 },
  separator: { height: 3 },
  row: { minHeight: 104, flexDirection: "row", alignItems: "center", gap: 12, borderRadius: 17, paddingHorizontal: 12, paddingVertical: 13 },
  rowPressed: { backgroundColor: colors.surfaceRaised },
  iconWrap: { width: 44, height: 44, borderRadius: 15, alignItems: "center", justifyContent: "center", backgroundColor: colors.violet950 },
  liveDot: { position: "absolute", right: -1, top: -1, width: 10, height: 10, borderRadius: 6, borderWidth: 2, borderColor: colors.background, backgroundColor: colors.emerald500 },
  rowBody: { flex: 1, minWidth: 0 },
  rowTitleLine: { flexDirection: "row", alignItems: "center", gap: 8 },
  rowTitle: { flex: 1, color: colors.zinc100, fontSize: 14, fontWeight: "700" },
  time: { color: colors.zinc600, fontSize: 10 },
  workflow: { marginTop: 3, color: colors.zinc500, fontSize: 11 },
  rowFooter: { marginTop: 9, flexDirection: "row", alignItems: "center", gap: 8 },
  reply: { color: colors.amber300, fontSize: 9, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.4 },
  center: { flex: 1, minHeight: 280, alignItems: "center", justifyContent: "center", padding: 34 },
  emptyIcon: { width: 54, height: 54, borderRadius: 18, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface },
  emptyTitle: { marginTop: 15, color: colors.zinc300, fontSize: 16, fontWeight: "700" },
  emptyText: { marginTop: 7, maxWidth: 280, color: colors.zinc600, fontSize: 12, lineHeight: 18, textAlign: "center" },
  pressed: { opacity: 0.7 },
});
