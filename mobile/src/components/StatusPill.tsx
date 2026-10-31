import { StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";
import type { JobStatus } from "../types";
import { humanize } from "../utils";

const statusColors: Record<JobStatus, string> = {
  queued: colors.zinc400,
  running: colors.sky300,
  review_required: colors.amber300,
  succeeded: colors.emerald300,
  failed: colors.rose300,
};

export function StatusPill({ status, compact = false }: { status: JobStatus; compact?: boolean }) {
  const tone = statusColors[status];
  return (
    <View style={[styles.pill, compact && styles.compact, { backgroundColor: `${tone}18` }]}>
      <View style={[styles.dot, { backgroundColor: tone }]} />
      <Text style={[styles.text, compact && styles.compactText, { color: tone }]}>{humanize(status)}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 6 },
  compact: { paddingHorizontal: 8, paddingVertical: 4, gap: 5 },
  dot: { width: 5, height: 5, borderRadius: 5 },
  text: { fontSize: 10, lineHeight: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.5 },
  compactText: { fontSize: 9 },
});
