{{/* Service name: the release name unless nameOverride is set. */}}
{{- define "service.name" -}}
{{- default .Release.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels used to find this service's pods. Must never change after the first install. */}}
{{- define "service.selectorLabels" -}}
app.kubernetes.io/name: {{ include "service.name" . }}
{{- end -}}

{{/* Full set of labels for every object. */}}
{{- define "service.labels" -}}
{{ include "service.selectorLabels" . }}
app.kubernetes.io/part-of: {{ .Values.partOf }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Pod security settings. Call with a dict that has runAsUser and runAsGroup. */}}
{{- define "service.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: {{ .runAsUser }}
runAsGroup: {{ .runAsGroup }}
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Container security settings, the same for every container we run. */}}
{{- define "service.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}
