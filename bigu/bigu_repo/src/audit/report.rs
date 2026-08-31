//! Assembles the sibling modules into one printable answer.
//!
//! Each of the other modules answers a single question, which is right for a
//! caller who knows what went wrong and wrong for a caller who does not. When a
//! property test fails at three in the morning, the useful artifact is one block
//! of text carrying every fact at once: whether the representation is legal,
//! what it costs, which value it actually is, and — on demand — the limb table
//! behind all three.
//!
//! Nothing is computed here. Every line printed comes from
//! [`crate::audit::invariant`], [`crate::audit::footprint`],
//! [`crate::audit::fingerprint`] or [`crate::audit::dump`]; this module only
//! decides the order and the wording, which is why a change to any of those
//! shows up in the report without being copied into it.

use core::fmt;

use crate::audit::dump;
use crate::audit::fingerprint::{self, Fingerprint};
use crate::audit::footprint::{self, Footprint};
use crate::audit::invariant::{self, Violation};
use crate::bigu::BigU;

/// Everything the subsystem knows about one labelled value.
#[derive(Debug, Clone)]
pub struct AuditReport {
    label: String,
    violations: Vec<Violation>,
    footprint: Footprint,
    fingerprint: Fingerprint,
    dump: Option<String>,
}

impl AuditReport {
    /// Audits `value` under `label`, without the limb table.
    ///
    /// ```
    /// use bigu::{audit::AuditReport, BigU};
    /// let r = AuditReport::of("modulus", &BigU::from(97u32));
    /// assert!(r.is_clean());
    /// assert_eq!(r.footprint().limbs, 1);
    /// ```
    pub fn of(label: &str, value: &BigU) -> AuditReport {
        AuditReport {
            label: label.to_string(),
            violations: invariant::check_bigu(value),
            footprint: footprint::of(value),
            fingerprint: fingerprint::of(value),
            dump: None,
        }
    }

    /// Audits `value` and keeps its limb table, gutter included.
    ///
    /// ```
    /// use bigu::{audit::AuditReport, BigU};
    /// let r = AuditReport::detailed("operand", &BigU::from(0x41u32));
    /// assert!(r.to_string().contains("0x00000041"));
    /// ```
    pub fn detailed(label: &str, value: &BigU) -> AuditReport {
        AuditReport {
            dump: Some(dump::limb_table(value, true)),
            ..AuditReport::of(label, value)
        }
    }

    /// The label this report was filed under.
    ///
    /// ```
    /// # use bigu::{audit::AuditReport, BigU};
    /// assert_eq!(AuditReport::of("n", &BigU::zero()).label(), "n");
    /// ```
    pub fn label(&self) -> &str {
        &self.label
    }

    /// The canonical-form rules the value broke, empty when it is well formed.
    ///
    /// ```
    /// # use bigu::{audit::AuditReport, BigU};
    /// assert!(AuditReport::of("n", &BigU::from(5u32)).violations().is_empty());
    /// ```
    pub fn violations(&self) -> &[Violation] {
        &self.violations
    }

    /// What the value costs.
    ///
    /// ```
    /// # use bigu::{audit::AuditReport, BigU};
    /// assert_eq!(AuditReport::of("z", &BigU::zero()).footprint().heap_bytes, 0);
    /// ```
    pub fn footprint(&self) -> Footprint {
        self.footprint
    }

    /// The run-independent digest of the value.
    ///
    /// ```
    /// # use bigu::{audit::AuditReport, BigU};
    /// let r = AuditReport::of("v", &BigU::from(42u32));
    /// assert_eq!(r.fingerprint(), bigu::audit::fingerprint::of(&BigU::from(42u32)));
    /// ```
    pub fn fingerprint(&self) -> Fingerprint {
        self.fingerprint
    }

    /// Whether the value broke no rule.
    ///
    /// ```
    /// # use bigu::{audit::AuditReport, BigU};
    /// let wide = BigU::from(1u32) << 64;
    /// assert!(AuditReport::of("v", &wide).is_clean());
    /// ```
    pub fn is_clean(&self) -> bool {
        self.violations.is_empty()
    }

    /// A single line suitable for a log: label, verdict, width and digest.
    ///
    /// ```
    /// use bigu::{audit::AuditReport, BigU};
    /// let line = AuditReport::of("n", &BigU::from(1u32)).summary();
    /// assert!(line.starts_with("n: ok, 1 limbs"));
    /// assert_eq!(line.lines().count(), 1);
    /// ```
    pub fn summary(&self) -> String {
        let verdict = if self.is_clean() {
            "ok".to_string()
        } else {
            format!("{} violations", self.violations.len())
        };
        format!(
            "{}: {verdict}, {} limbs, {} bytes, fp {}",
            self.label,
            self.footprint.limbs,
            self.footprint.total_bytes(),
            self.fingerprint
        )
    }
}

impl fmt::Display for AuditReport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let verdict = if self.is_clean() { "ok" } else { "FAILED" };
        writeln!(f, "audit {:?}: {verdict}", self.label)?;
        for v in &self.violations {
            writeln!(f, "  violation: {v}")?;
        }
        writeln!(f, "  fingerprint {}", self.fingerprint)?;
        writeln!(f, "  footprint   {}", self.footprint)?;
        match &self.dump {
            None => Ok(()),
            Some(text) => {
                for line in text.lines() {
                    writeln!(f, "  {line}")?;
                }
                Ok(())
            }
        }
    }
}

/// Audits a labelled collection in one pass, preserving order.
///
/// ```
/// use bigu::{audit::report, BigU};
/// let (a, b) = (BigU::from(1u32), BigU::zero());
/// let reports = report::labelled(&[("a", &a), ("b", &b)]);
/// assert_eq!(reports.len(), 2);
/// assert_eq!(reports[1].label(), "b");
/// ```
pub fn labelled(items: &[(&str, &BigU)]) -> Vec<AuditReport> {
    items
        .iter()
        .map(|(label, value)| AuditReport::of(label, value))
        .collect()
}

/// Renders a collection of reports, worst first, with a count line on top.
///
/// ```
/// use bigu::{audit::report, BigU};
/// let (a, b) = (BigU::from(1u32), BigU::zero());
/// let text = report::render_all(&report::labelled(&[("a", &a), ("b", &b)]));
/// assert!(text.starts_with("2 values audited, 0 with violations"));
/// ```
pub fn render_all(reports: &[AuditReport]) -> String {
    let failed = reports.iter().filter(|r| !r.is_clean()).count();
    let mut out = format!(
        "{} values audited, {failed} with violations\n",
        reports.len()
    );
    for r in reports.iter().filter(|r| !r.is_clean()) {
        out.push_str(&r.to_string());
    }
    for r in reports.iter().filter(|r| r.is_clean()) {
        out.push_str(&format!("{}\n", r.summary()));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_clean_report_names_no_violation() {
        let r = AuditReport::of("x", &BigU::from(u64::MAX));
        assert!(r.is_clean());
        let text = r.to_string();
        assert!(text.starts_with("audit \"x\": ok"));
        assert!(!text.contains("violation"));
        assert!(text.contains("fingerprint"));
        assert!(text.contains("footprint"));
    }

    #[test]
    fn a_corrupt_value_is_reported_not_asserted() {
        let bad = BigU { limbs: vec![9, 0] };
        let r = AuditReport::of("corrupt", &bad);
        assert!(!r.is_clean());
        assert_eq!(r.violations().len(), 2);
        let text = r.to_string();
        assert!(text.contains("audit \"corrupt\": FAILED"));
        assert!(text.contains("limb 1 is a trailing zero"));
        assert!(r.summary().contains("2 violations"));
    }

    #[test]
    fn the_dump_is_indented_under_the_report() {
        let r = AuditReport::detailed("d", &BigU::from(0x4142_4344u32));
        let text = r.to_string();
        assert!(text.contains("ABCD"));
        assert!(text.lines().all(|l| l.starts_with("audit") || l.starts_with("  ")));
    }

    #[test]
    fn the_fingerprint_matches_the_module_that_produced_it() {
        let v = BigU::from(123_456_789u32);
        assert_eq!(AuditReport::of("v", &v).fingerprint(), fingerprint::of(&v));
        assert_eq!(AuditReport::of("v", &v).footprint(), footprint::of(&v));
    }

    #[test]
    fn a_collection_puts_the_failures_first() {
        let good = BigU::from(1u32);
        let bad = BigU { limbs: vec![1, 0] };
        let text = render_all(&labelled(&[("good", &good), ("bad", &bad)]));
        let first = text.lines().nth(1).unwrap();
        assert!(first.contains("bad"));
        assert!(text.starts_with("2 values audited, 1 with violations"));
    }

    #[test]
    fn summaries_stay_on_one_line_even_for_wide_values() {
        let wide = BigU::from(1u32) << 8192;
        let line = AuditReport::of("wide", &wide).summary();
        assert_eq!(line.lines().count(), 1);
        assert!(line.contains("257 limbs"));
    }
}
