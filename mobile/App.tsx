import AsyncStorage from "@react-native-async-storage/async-storage";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { ActivityIndicator, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { AgentListScreen } from "./src/screens/AgentListScreen";
import { AgentRunScreen } from "./src/screens/AgentRunScreen";
import { SettingsScreen } from "./src/screens/SettingsScreen";
import type { Job } from "./src/types";
import { colors } from "./src/theme";

const API_URL_KEY = "clinical-ai-api-url";
const LOCAL_API_URL = "http://localhost:8000";
const ANDROID_EMULATOR_API_URL = "http://127.0.0.1:8000";
const DEFAULT_API_URL = process.env.EXPO_PUBLIC_API_URL
  ?? (Platform.OS === "android" ? ANDROID_EMULATOR_API_URL : LOCAL_API_URL);

type Screen = "agents" | "run" | "settings";

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <AppRoot />
    </SafeAreaProvider>
  );
}

function AppRoot() {
  const [screen, setScreen] = useState<Screen>("agents");
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [apiUrl, setApiUrl] = useState(DEFAULT_API_URL);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(API_URL_KEY)
      .then(async (saved) => {
        // The Android development command establishes an ADB reverse tunnel to
        // the host API. Migrate earlier emulator defaults to that tunnel.
        const previousEmulatorDefaults = new Set([
          LOCAL_API_URL,
          ANDROID_EMULATOR_API_URL,
          "http://10.0.2.2:8000",
        ]);
        const shouldMigrate = Platform.OS === "android"
          && Boolean(saved)
          && saved !== DEFAULT_API_URL
          && previousEmulatorDefaults.has(saved!);
        const resolved = !saved || shouldMigrate ? DEFAULT_API_URL : saved;
        if (shouldMigrate) await AsyncStorage.setItem(API_URL_KEY, resolved);
        setApiUrl(resolved);
      })
      .finally(() => setReady(true));
  }, []);

  const openJob = (job: Job) => {
    setSelectedJob(job);
    setScreen("run");
  };

  const saveApiUrl = async (value: string) => {
    const normalized = value.trim().replace(/\/+$/, "");
    await AsyncStorage.setItem(API_URL_KEY, normalized);
    setApiUrl(normalized);
  };

  if (!ready) {
    return (
      <SafeAreaView style={styles.loading}>
        <View style={styles.loadingMark}><MaterialCommunityIcons name="flask-outline" size={24} color={colors.violet200} /></View>
        <ActivityIndicator color={colors.violet400} />
        <Text style={styles.loadingText}>Opening agent console…</Text>
      </SafeAreaView>
    );
  }

  if (screen === "run" && selectedJob) {
    return <AgentRunScreen apiUrl={apiUrl} initialJob={selectedJob} onBack={() => setScreen("agents")} />;
  }

  return (
    <SafeAreaView style={styles.app} edges={["top", "bottom", "left", "right"]}>
      <View style={styles.content}>
        {screen === "agents"
          ? <AgentListScreen apiUrl={apiUrl} onOpenJob={openJob} onOpenSettings={() => setScreen("settings")} />
          : <SettingsScreen apiUrl={apiUrl} onSave={saveApiUrl} />}
      </View>
      <BottomTabs active={screen} onChange={setScreen} />
    </SafeAreaView>
  );
}

function BottomTabs({ active, onChange }: { active: Screen; onChange: (screen: "agents" | "settings") => void }) {
  return (
    <View style={styles.tabs}>
      <TabButton icon="robot-outline" label="Agents" active={active === "agents"} onPress={() => onChange("agents")} />
      <TabButton icon="cog-outline" label="Settings" active={active === "settings"} onPress={() => onChange("settings")} />
    </View>
  );
}

function TabButton({ icon, label, active, onPress }: { icon: keyof typeof MaterialCommunityIcons.glyphMap; label: string; active: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} onPress={onPress} style={({ pressed }) => [styles.tab, pressed && styles.pressed]}>
      <MaterialCommunityIcons name={icon} size={22} color={active ? colors.violet200 : colors.zinc600} />
      <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text>
      {active && <View style={styles.tabDot} />}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  app: { flex: 1, backgroundColor: colors.background },
  content: { flex: 1 },
  loading: { flex: 1, alignItems: "center", justifyContent: "center", gap: 14, backgroundColor: colors.background },
  loadingMark: { width: 52, height: 52, borderRadius: 18, alignItems: "center", justifyContent: "center", backgroundColor: colors.violet950, marginBottom: 4 },
  loadingText: { color: colors.zinc500, fontSize: 13 },
  tabs: { flexDirection: "row", borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border, backgroundColor: colors.surface, paddingBottom: 6 },
  tab: { flex: 1, height: 60, alignItems: "center", justifyContent: "center", gap: 2 },
  tabLabel: { color: colors.zinc600, fontSize: 10, fontWeight: "700" },
  tabLabelActive: { color: colors.violet200 },
  tabDot: { position: "absolute", top: 4, width: 18, height: 2, borderRadius: 2, backgroundColor: colors.violet400 },
  pressed: { opacity: 0.65 },
});
