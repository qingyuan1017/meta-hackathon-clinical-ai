import { MaterialCommunityIcons } from "@expo/vector-icons";
import { useEffect, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { mobileApi } from "../api";
import { ScreenHeader } from "../components/ScreenHeader";
import { colors } from "../theme";

export function SettingsScreen({ apiUrl, onSave }: { apiUrl: string; onSave: (value: string) => Promise<void> }) {
  const [value, setValue] = useState(apiUrl);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => setValue(apiUrl), [apiUrl]);

  const normalized = value.trim().replace(/\/+$/, "");
  const valid = /^https?:\/\/.+/.test(normalized);

  const test = async () => {
    if (!valid) return;
    setTesting(true);
    try {
      const health = await mobileApi.health(normalized);
      setResult({ ok: true, message: `Connected · ${health.meta_model ?? "model not configured"}` });
    } catch (error) {
      setResult({ ok: false, message: error instanceof Error ? error.message : "Connection failed." });
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    if (!valid) return;
    setSaving(true);
    try {
      await onSave(normalized);
      setResult({ ok: true, message: "Backend address saved on this device." });
    } finally {
      setSaving(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScreenHeader eyebrow="Mobile app" title="Settings" />
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <View style={styles.heroIcon}><MaterialCommunityIcons name="server-network" size={27} color={colors.violet200} /></View>
        <Text style={styles.heading}>Connect to your Workbench</Text>
        <Text style={styles.intro}>The app talks directly to the existing FastAPI service. Credentials and model keys remain on the backend.</Text>

        <View style={styles.card}>
          <Text style={styles.label}>Backend URL</Text>
          <TextInput
            value={value}
            onChangeText={(next) => { setValue(next); setResult(null); }}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
            placeholder={Platform.OS === "android" ? "http://127.0.0.1:8000" : "http://192.168.1.20:8000"}
            placeholderTextColor={colors.zinc600}
            selectionColor={colors.violet400}
            style={styles.input}
          />
          {!valid && value.length > 0 && <Text style={styles.validation}>Enter a complete http:// or https:// address.</Text>}
          <View style={styles.actions}>
            <Pressable disabled={!valid || testing} onPress={test} style={({ pressed }) => [styles.secondaryButton, (!valid || testing) && styles.disabled, pressed && styles.pressed]}>
              {testing ? <ActivityIndicator size="small" color={colors.zinc200} /> : <MaterialCommunityIcons name="access-point" size={17} color={colors.zinc200} />}
              <Text style={styles.secondaryText}>Test</Text>
            </Pressable>
            <Pressable disabled={!valid || saving} onPress={save} style={({ pressed }) => [styles.primaryButton, (!valid || saving) && styles.disabled, pressed && styles.pressed]}>
              {saving ? <ActivityIndicator size="small" color={colors.white} /> : <MaterialCommunityIcons name="content-save-outline" size={17} color={colors.white} />}
              <Text style={styles.primaryText}>Save</Text>
            </Pressable>
          </View>
          {result && <View style={[styles.result, result.ok ? styles.resultOk : styles.resultError]}><MaterialCommunityIcons name={result.ok ? "check-circle-outline" : "alert-circle-outline"} size={17} color={result.ok ? colors.emerald300 : colors.rose300} /><Text style={[styles.resultText, { color: result.ok ? colors.emerald300 : colors.rose300 }]}>{result.message}</Text></View>}
        </View>

        <View style={styles.note}>
          <MaterialCommunityIcons name="information-outline" size={19} color={colors.sky300} />
          <Text style={styles.noteText}>Android emulator: use http://127.0.0.1:8000 with the ADB reverse tunnel. Physical phone: use the computer&apos;s LAN address and allow inbound traffic to port 8000.</Text>
        </View>

        <View style={styles.securityCard}>
          <Text style={styles.securityTitle}>Clinical safety boundary</Text>
          <Text style={styles.securityText}>This app displays sanitized agent traces and draft artifacts. Do not use it for PHI or identifiable patient data. All outputs require qualified review.</Text>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: 20, paddingBottom: 40 },
  heroIcon: { width: 56, height: 56, alignItems: "center", justifyContent: "center", borderRadius: 19, backgroundColor: colors.violet950 },
  heading: { marginTop: 18, color: colors.zinc100, fontSize: 20, fontWeight: "700", letterSpacing: -0.3 },
  intro: { marginTop: 8, color: colors.zinc500, fontSize: 12, lineHeight: 19 },
  card: { marginTop: 24, borderRadius: 19, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceRaised, padding: 15 },
  label: { color: colors.zinc400, fontSize: 10, fontWeight: "800", textTransform: "uppercase", letterSpacing: 1 },
  input: { marginTop: 10, height: 48, borderRadius: 14, borderWidth: 1, borderColor: colors.borderStrong, backgroundColor: colors.background, paddingHorizontal: 13, color: colors.zinc100, fontSize: 13 },
  validation: { marginTop: 7, color: colors.rose300, fontSize: 10 },
  actions: { marginTop: 12, flexDirection: "row", gap: 9 },
  secondaryButton: { flex: 1, height: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7, borderRadius: 13, borderWidth: 1, borderColor: colors.borderStrong },
  primaryButton: { flex: 1, height: 44, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7, borderRadius: 13, backgroundColor: colors.violet500 },
  secondaryText: { color: colors.zinc200, fontSize: 12, fontWeight: "800" },
  primaryText: { color: colors.white, fontSize: 12, fontWeight: "800" },
  result: { marginTop: 12, flexDirection: "row", alignItems: "center", gap: 8, borderRadius: 12, paddingHorizontal: 11, paddingVertical: 9 },
  resultOk: { backgroundColor: `${colors.emerald500}12` },
  resultError: { backgroundColor: `${colors.rose500}12` },
  resultText: { flex: 1, fontSize: 10, lineHeight: 15 },
  note: { marginTop: 14, flexDirection: "row", alignItems: "flex-start", gap: 10, borderRadius: 16, borderWidth: 1, borderColor: `${colors.sky500}28`, backgroundColor: `${colors.sky500}0D`, padding: 14 },
  noteText: { flex: 1, color: colors.sky300, opacity: 0.78, fontSize: 11, lineHeight: 17 },
  securityCard: { marginTop: 14, borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 14 },
  securityTitle: { color: colors.zinc300, fontSize: 11, fontWeight: "800" },
  securityText: { marginTop: 6, color: colors.zinc600, fontSize: 10, lineHeight: 16 },
  disabled: { opacity: 0.4 },
  pressed: { opacity: 0.65 },
});
