import { MaterialCommunityIcons } from "@expo/vector-icons";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "../theme";

export function ScreenHeader({ eyebrow, title, actionIcon, actionLabel, onAction }: { eyebrow: string; title: string; actionIcon?: keyof typeof MaterialCommunityIcons.glyphMap; actionLabel?: string; onAction?: () => void }) {
  return (
    <View style={styles.header}>
      <View>
        <Text style={styles.eyebrow}>{eyebrow}</Text>
        <Text style={styles.title}>{title}</Text>
      </View>
      {actionIcon && onAction && (
        <Pressable accessibilityRole="button" accessibilityLabel={actionLabel} onPress={onAction} style={({ pressed }) => [styles.action, pressed && styles.pressed]}>
          <MaterialCommunityIcons name={actionIcon} size={20} color={colors.zinc300} />
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  header: { minHeight: 82, flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 20, paddingVertical: 14, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  eyebrow: { color: colors.violet300, fontSize: 10, fontWeight: "800", letterSpacing: 1.4, textTransform: "uppercase" },
  title: { marginTop: 3, color: colors.white, fontSize: 24, fontWeight: "700", letterSpacing: -0.6 },
  action: { width: 42, height: 42, borderRadius: 14, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceRaised },
  pressed: { opacity: 0.65 },
});
