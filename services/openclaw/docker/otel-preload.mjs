import pkgNodeSDK from "@opentelemetry/sdk-node";
const { NodeSDK } = pkgNodeSDK;

import pkgAutoInst from "@opentelemetry/auto-instrumentations-node";
const { getNodeAutoInstrumentations } = pkgAutoInst;

import pkgOTLP from "@opentelemetry/exporter-trace-otlp-proto";
const { OTLPTraceExporter } = pkgOTLP;

import pkgResources from "@opentelemetry/resources";
const { resourceFromAttributes } = pkgResources;

import pkgSemantic from "@opentelemetry/semantic-conventions";
const { ATTR_SERVICE_NAME } = pkgSemantic;

import pkgCore from "@opentelemetry/core";
const {
  CompositePropagator,
  W3CBaggagePropagator,
  W3CTraceContextPropagator,
} = pkgCore;

const sdk = new NodeSDK({
  resource: resourceFromAttributes({
    [ATTR_SERVICE_NAME]: process.env.OTEL_SERVICE_NAME || "openclaw-gateway",
  }),
  textMapPropagator: new CompositePropagator({
    propagators: [new W3CTraceContextPropagator(), new W3CBaggagePropagator()],
  }),
  instrumentations: [getNodeAutoInstrumentations()],
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT 
      ? (process.env.OTEL_EXPORTER_OTLP_ENDPOINT.endsWith("/v1/traces") 
          ? process.env.OTEL_EXPORTER_OTLP_ENDPOINT 
          : `${process.env.OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces`)
      : "http://otel-collector:4318/v1/traces",
  }),
});

sdk.start();
process.env.OPENCLAW_OTEL_PRELOADED = "1";

const shutdown = () => {
  sdk.shutdown()
    .then(() => console.log("OTel SDK shut down"))
    .catch((err) => console.log("Error shutting down OTel SDK", err))
    .finally(() => process.exit(0));
};

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
