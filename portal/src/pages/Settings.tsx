import { useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, Check } from "lucide-react";
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

  const [selectedTz, setSelectedTz] = useState(currentTimezone);
  const [dirty, setDirty] = useState(false);

  // Sync when profile loads
  useEffect(() => {
    if (profile.data) {
      const tz =
        (profile.data.settling_config?.timezone as string) || "UTC";
      setSelectedTz(tz);
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
      toast("Timezone updated");
    },
    onError: () => {
      toast("Failed to save settings", "destructive");
    },
  });

  function handleSave() {
    saveMutation.mutate({ timezone: selectedTz });
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
              setDirty(e.target.value !== currentTimezone);
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

          <div className="mt-4 flex items-center gap-3">
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
            {!dirty && profile.data && (
              <span className="text-xs text-muted-foreground">
                Current: {formatTzLabel(currentTimezone)}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
