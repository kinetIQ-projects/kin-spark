import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, Check, Calendar, Link2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { ClientProfile, SettingsUpdate } from "@/lib/types";
import { toast } from "@/components/ui/toaster";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorCard } from "@/components/common/ErrorCard";

// Common timezones shown at the top of the dropdown for quick access
const COMMON_TIMEZONES = [
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "Pacific/Honolulu",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Australia/Sydney",
  "UTC",
];

function formatTzLabel(tz: string): string {
  return tz.replace(/_/g, " ").replace(/\//g, " / ");
}

export function Settings() {
  const queryClient = useQueryClient();

  const profile = useQuery({
    queryKey: ["profile"],
    queryFn: () => apiFetch<ClientProfile>("/me"),
  });

  const currentTimezone =
    (profile.data?.settling_config?.timezone as string) || "UTC";
  const currentCalendly =
    (profile.data?.settling_config?.calendly_link as string) || "";
  const currentHubspot =
    (profile.data?.settling_config?.hubspot_api_key as string) || "";

  const [selectedTz, setSelectedTz] = useState(currentTimezone);
  const [calendlyLink, setCalendlyLink] = useState(currentCalendly);
  const [hubspotKey, setHubspotKey] = useState(currentHubspot);
  const [dirty, setDirty] = useState(false);

  // Sync when profile loads
  useEffect(() => {
    if (profile.data) {
      const tz =
        (profile.data.settling_config?.timezone as string) || "UTC";
      setSelectedTz(tz);
      setCalendlyLink(
        (profile.data.settling_config?.calendly_link as string) || ""
      );
      setHubspotKey(
        (profile.data.settling_config?.hubspot_api_key as string) || ""
      );
      setDirty(false);
    }
  }, [profile.data]);

  // Build the full timezone list: common at top, then all IANA sorted.
  // Intl.supportedValuesOf exists in modern browsers but isn't in all TS libs.
  const allTimezones = useMemo((): string[] => {
    try {
      const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
      if (intl.supportedValuesOf) return intl.supportedValuesOf("timeZone");
    } catch {
      // not available
    }
    return COMMON_TIMEZONES;
  }, []);

  const otherTimezones = useMemo(
    () =>
      allTimezones
        .filter((tz: string) => !COMMON_TIMEZONES.includes(tz))
        .sort(),
    [allTimezones]
  );

  const saveMutation = useMutation({
    mutationFn: (update: SettingsUpdate) =>
      apiFetch<ClientProfile>("/settings", {
        method: "PATCH",
        body: JSON.stringify(update),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["profile"], data);
      setDirty(false);
      toast("Settings saved");
    },
    onError: () => {
      toast("Failed to save settings", "destructive");
    },
  });

  function handleSave() {
    const update: SettingsUpdate = {};
    if (selectedTz !== currentTimezone) update.timezone = selectedTz;
    if (calendlyLink !== currentCalendly) update.calendly_link = calendlyLink;
    if (hubspotKey !== currentHubspot) update.hubspot_api_key = hubspotKey;
    saveMutation.mutate(update);
  }

  function checkDirty(tz: string, cal: string, hs: string) {
    setDirty(
      tz !== currentTimezone || cal !== currentCalendly || hs !== currentHubspot
    );
  }

  if (profile.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  if (profile.isError) {
    return (
      <div className="mt-8">
        <ErrorCard
          message="Failed to load settings"
          onRetry={() => profile.refetch()}
        />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>

      <div className="mt-8 max-w-lg space-y-6">
        {/* Timezone */}
        <div className="rounded-lg border p-5">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Globe className="h-4 w-4 text-muted-foreground" />
            Timezone
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Sets the time shown in Spark&apos;s responses. Choose the
            timezone that matches your business location.
          </p>

          <select
            value={selectedTz}
            onChange={(e) => {
              setSelectedTz(e.target.value);
              checkDirty(e.target.value, calendlyLink, hubspotKey);
            }}
            className="mt-3 h-9 w-full rounded-md border bg-background px-3 text-sm"
          >
            <optgroup label="Common">
              {COMMON_TIMEZONES.map((tz) => (
                <option key={tz} value={tz}>
                  {formatTzLabel(tz)}
                </option>
              ))}
            </optgroup>
            <optgroup label="All Timezones">
              {otherTimezones.map((tz) => (
                <option key={tz} value={tz}>
                  {formatTzLabel(tz)}
                </option>
              ))}
            </optgroup>
          </select>

        </div>
        {/* Calendly Link */}
        <div className="rounded-lg border p-5">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Calendar className="h-4 w-4 text-muted-foreground" />
            Calendly Link
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Spark will share this booking link when a visitor wants to
            schedule a call.
          </p>
          <input
            type="url"
            value={calendlyLink}
            onChange={(e) => {
              setCalendlyLink(e.target.value);
              checkDirty(selectedTz, e.target.value, hubspotKey);
            }}
            placeholder="https://calendly.com/your-team/meeting"
            className="mt-3 h-9 w-full rounded-md border bg-background px-3 text-sm"
          />
        </div>

        {/* HubSpot API Key */}
        <div className="rounded-lg border p-5">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Link2 className="h-4 w-4 text-muted-foreground" />
            HubSpot Integration
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Connect HubSpot to automatically sync leads and conversation
            summaries. Paste your Private App access token.
          </p>
          <input
            type="password"
            value={hubspotKey}
            onChange={(e) => {
              setHubspotKey(e.target.value);
              checkDirty(selectedTz, calendlyLink, e.target.value);
            }}
            placeholder="pat-na1-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
            className="mt-3 h-9 w-full rounded-md border bg-background px-3 text-sm font-mono"
          />
          {hubspotKey && (
            <p className="mt-2 text-xs text-muted-foreground">
              Requires scopes: crm.objects.contacts.write,
              crm.objects.contacts.read, crm.objects.notes.write
            </p>
          )}
        </div>

        {/* Save button */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={!dirty || saveMutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:pointer-events-none disabled:opacity-50"
          >
            {saveMutation.isPending ? (
              "Saving..."
            ) : (
              <>
                <Check className="h-3.5 w-3.5" />
                Save
              </>
            )}
          </button>
          {!dirty && (
            <span className="text-xs text-muted-foreground">
              All settings saved
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
