import { describe, expect, it } from "vitest";
import {
  activityKey,
  formatActivityTimestamp,
  matchesOrigin,
  sortActivityEntries,
} from "./activity";

describe("activity evidence", () => {
  it("shows full source time in explicit UTC and labels missing dates", () => {
    expect(formatActivityTimestamp("2020-03-04T05:06:07+02:00")).toContain(
      "04.03.2020",
    );
    expect(formatActivityTimestamp("2020-03-04T05:06:07+02:00")).toContain(
      "03:06:07 UTC",
    );
    expect(formatActivityTimestamp(null)).toContain("Udatert");
  });
  it("sorts actual instants with undated events last", () => {
    expect(
      sortActivityEntries([
        { timestamp: null },
        { timestamp: "2020-01-01T01:00:00Z" },
        { timestamp: "2020-01-01T02:30:00+02:00" },
      ]).map((e) => e.timestamp),
    ).toEqual(["2020-01-01T01:00:00Z", "2020-01-01T02:30:00+02:00", null]);
  });
  it("keeps unknown and test events separate from operations", () => {
    expect(matchesOrigin({ origin: "test" }, "operational")).toBe(false);
    expect(matchesOrigin({}, "operational")).toBe(false);
    expect(matchesOrigin({}, "unknown")).toBe(true);
  });
  it("identifies occurrences by source ID even when their messages match", () => {
    const row = {
      timestamp: null,
      message: "same warning",
      project_name: "Testprosjekt",
    };
    expect(activityKey({ ...row, event_id: "a" })).not.toBe(
      activityKey({ ...row, event_id: "b" }),
    );
  });
});
