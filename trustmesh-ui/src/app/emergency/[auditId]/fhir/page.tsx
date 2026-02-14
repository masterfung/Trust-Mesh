"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { api, FhirResource } from "@/lib/api";
import {
  ShieldAlert,
  User,
  AlertTriangle,
  Pill,
  HeartPulse,
  Activity,
  Users,
  FileText,
  Clock,
  Building2,
  BadgeCheck,
} from "lucide-react";

const RESOURCE_CONFIG: Record<string, { icon: typeof User; color: string; label: string }> = {
  Patient: { icon: User, color: "text-sky-400 bg-sky-500/10 border-sky-500/20", label: "Patient Identity" },
  AllergyIntolerance: { icon: AlertTriangle, color: "text-red-400 bg-red-500/10 border-red-500/20", label: "Allergy / Intolerance" },
  MedicationStatement: { icon: Pill, color: "text-purple-400 bg-purple-500/10 border-purple-500/20", label: "Medication" },
  Condition: { icon: HeartPulse, color: "text-amber-400 bg-amber-500/10 border-amber-500/20", label: "Medical Condition" },
  Observation: { icon: Activity, color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20", label: "Clinical Observation" },
  RelatedPerson: { icon: Users, color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20", label: "Emergency Contact" },
};

function ResourceCard({ resource }: { resource: FhirResource }) {
  const rtype = resource.resourceType;
  const config = RESOURCE_CONFIG[rtype] || { icon: FileText, color: "text-gray-400 bg-gray-500/10 border-gray-500/20", label: rtype };
  const Icon = config.icon;
  const tm = resource._trustmesh;

  const getTitle = () => {
    if (rtype === "Patient") return resource.name?.[0]?.text || "Unknown Patient";
    if (rtype === "AllergyIntolerance") return resource.code?.text || "Allergy";
    if (rtype === "MedicationStatement") return resource.medicationCodeableConcept?.text || "Medication";
    if (rtype === "Condition") return resource.code?.text || "Condition";
    if (rtype === "Observation") return resource.code?.text || "Observation";
    if (rtype === "RelatedPerson") return resource.name?.[0]?.text || "Contact";
    return rtype;
  };

  const getContent = () => {
    if (resource.note?.[0]?.text) return resource.note[0].text;
    if (resource.valueString) return resource.valueString;
    if (resource.communication?.[0]?.text) return resource.communication[0].text;
    if (rtype === "Patient") {
      const parts = [];
      const name = resource.name?.[0];
      if (name?.given) parts.push(`Given: ${name.given.join(" ")}`);
      if (name?.family) parts.push(`Family: ${name.family}`);
      return parts.join(", ") || null;
    }
    return null;
  };

  return (
    <div className="rounded-2xl border bg-card/50 border-card-border overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-card-border/50">
        <div className={`p-2 rounded-xl border ${config.color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-foreground">{getTitle()}</p>
          <p className="text-[11px] text-muted-foreground">{config.label}</p>
        </div>
        <div className="flex items-center gap-1.5">
          {tm?.visibility && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
              {tm.visibility}
            </span>
          )}
          {tm?.emergency_accessible && (
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 flex items-center gap-1">
              <ShieldAlert className="w-3 h-3" />
              EMR
            </span>
          )}
        </div>
      </div>

      <div className="px-4 py-3 space-y-2">
        {getContent() && (
          <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-wrap">
            {getContent()}
          </p>
        )}

        {rtype === "AllergyIntolerance" && tm?.substances && tm.substances.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap mt-1">
            <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">Identified substances:</span>
            {tm.substances.map((s) => (
              <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 font-semibold">
                {s}
              </span>
            ))}
          </div>
        )}

        {resource.clinicalStatus?.coding?.[0]?.code && (
          <p className="text-[10px] text-muted-foreground">
            Clinical status: <span className="text-foreground font-medium">{resource.clinicalStatus.coding[0].code}</span>
          </p>
        )}
      </div>
    </div>
  );
}

export default function FhirViewerPage() {
  const params = useParams();
  const auditId = params.auditId as string;

  const { data: bundle, isLoading, error } = useQuery({
    queryKey: ["fhir-bundle", auditId],
    queryFn: () => api.getEmergencyFhirBundle(auditId),
  });

  if (isLoading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-muted-foreground animate-pulse">Loading FHIR Bundle...</div>
      </div>
    );
  }

  if (error || !bundle) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-3">
          <ShieldAlert className="w-12 h-12 text-red-400 mx-auto" />
          <div className="text-red-400 text-lg font-semibold">Failed to load FHIR Bundle</div>
          <p className="text-sm text-muted-foreground">
            {error?.message || "Bundle not found. The audit ID may be invalid."}
          </p>
          <p className="text-xs text-muted-foreground font-mono">{auditId}</p>
        </div>
      </div>
    );
  }

  const patient = bundle.entry.find((e) => e.resource.resourceType === "Patient")?.resource;
  const resources = bundle.entry.filter((e) => e.resource.resourceType !== "Patient");
  const emergency = bundle._trustmesh_emergency;

  // Group resources by type for summary
  const typeCounts: Record<string, number> = {};
  for (const entry of resources) {
    const rt = entry.resource.resourceType;
    typeCounts[rt] = (typeCounts[rt] || 0) + 1;
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
        {/* Emergency banner */}
        <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-4 space-y-3">
          <div className="flex items-center gap-2 text-red-400">
            <ShieldAlert className="w-5 h-5" />
            <span className="text-xs font-semibold uppercase tracking-wider">Emergency Medical Access — FHIR R4 Bundle</span>
          </div>
          <h1 className="text-2xl font-bold text-foreground">
            {patient?.name?.[0]?.text || "Patient"} — Medical Records
          </h1>
          {emergency && (
            <div className="flex flex-wrap gap-2">
              <span className="text-xs px-3 py-1 rounded-full bg-red-500/10 text-red-400 border border-red-500/20 flex items-center gap-1.5">
                <BadgeCheck className="w-3.5 h-3.5" />
                {emergency.access_role.replace(/_/g, " ")}
              </span>
              <span className="text-xs px-3 py-1 rounded-full bg-card border border-card-border text-muted-foreground flex items-center gap-1.5">
                <Building2 className="w-3.5 h-3.5" />
                {emergency.institution}
              </span>
              <span className="text-xs px-3 py-1 rounded-full bg-card border border-card-border text-muted-foreground font-mono flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5" />
                {emergency.case_id}
              </span>
            </div>
          )}
          <div className="flex items-center gap-4 text-[11px] text-muted-foreground">
            <span className="flex items-center gap-1">
              <Clock className="w-3.5 h-3.5" />
              {new Date(bundle.meta.lastUpdated).toLocaleString()}
            </span>
            <span>{bundle.total} resources</span>
            <span className="font-mono text-[10px]">Bundle/{bundle.id.slice(0, 8)}</span>
          </div>
        </div>

        {/* Data accessed summary */}
        <div className="rounded-2xl border border-card-border bg-card/30 p-4 space-y-2">
          <p className="text-xs font-semibold text-foreground uppercase tracking-wider">Data accessed</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(typeCounts).map(([type, count]) => {
              const config = RESOURCE_CONFIG[type];
              const Icon = config?.icon || FileText;
              return (
                <span key={type} className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-1.5 ${config?.color || "text-gray-400 bg-gray-500/10 border-gray-500/20"}`}>
                  <Icon className="w-3.5 h-3.5" />
                  {count} {config?.label || type}{count > 1 ? "s" : ""}
                </span>
              );
            })}
          </div>
          <div className="mt-2 pt-2 border-t border-card-border/50">
            <p className="text-[11px] text-muted-foreground">
              Capsule titles shared:{" "}
              {resources.map((e) => {
                const r = e.resource;
                const title = r.code?.text || r.medicationCodeableConcept?.text || r.name?.[0]?.text || r.resourceType;
                return title;
              }).join(" | ")}
            </p>
          </div>
        </div>

        {/* Patient card */}
        {patient && <ResourceCard resource={patient} />}

        {/* Divider */}
        <div className="flex items-center gap-3">
          <div className="h-px flex-1 bg-card-border" />
          <span className="text-xs text-muted-foreground">{resources.length} medical record{resources.length !== 1 ? "s" : ""}</span>
          <div className="h-px flex-1 bg-card-border" />
        </div>

        {/* Resources */}
        <div className="space-y-3">
          {resources.map((entry) => (
            <ResourceCard key={entry.fullUrl} resource={entry.resource} />
          ))}
        </div>

        {/* Raw JSON */}
        <details className="rounded-2xl border border-card-border overflow-hidden">
          <summary className="px-4 py-3 text-sm text-muted-foreground cursor-pointer hover:text-foreground transition-colors">
            View raw FHIR R4 JSON
          </summary>
          <pre className="px-4 py-3 text-xs text-muted-foreground bg-card/30 overflow-x-auto max-h-96 border-t border-card-border">
            {JSON.stringify(bundle, null, 2)}
          </pre>
        </details>

        {/* Footer */}
        <p className="text-center text-[10px] text-muted-foreground">
          FHIR R4 compliant | Generated by TrustMesh | Audit ID: <span className="font-mono">{auditId}</span>
        </p>
      </div>
    </div>
  );
}
