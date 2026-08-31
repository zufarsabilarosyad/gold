//! Renders the storage, not the number.
//!
//! [`crate::fmt`] and [`crate::radix`] already answer "what is this value?" in
//! any radix from 2 to 36. They are the wrong tool for the other question — "how
//! is this value laid out?" — because a decimal string deliberately hides the
//! limb boundaries, and those boundaries are where carry, shift and division
//! bugs live. A dump therefore prints one line per limb, in the order a written
//! number reads (most significant first), with the bit range each limb covers
//! spelled out so a failing bit index can be located by eye.
//!
//! The optional gutter is the one borrowed from `hexdump`: the four bytes of the
//! limb as printable ASCII, with anything unprintable shown as a dot. It costs
//! nothing to produce and immediately reveals when a "number" is really a
//! mis-parsed string of text.

use crate::audit::layout;
use crate::bigu::BigU;

/// Renders the four bytes of `limb` as printable ASCII, most-significant byte
/// first, substituting `.` for anything outside the printable range.
///
/// ```
/// use bigu::audit::dump;
/// assert_eq!(dump::ascii_cell(0x4142_4344), "ABCD");
/// assert_eq!(dump::ascii_cell(0), "....");
/// ```
pub fn ascii_cell(limb: u32) -> String {
    limb.to_be_bytes()
        .iter()
        .map(|&b| {
            if (0x20..0x7f).contains(&b) {
                b as char
            } else {
                '.'
            }
        })
        .collect()
}

/// Renders `v` as an indexed limb table, most-significant limb first.
///
/// Each row carries the little-endian limb index, the limb in fixed-width hex,
/// and the half-open bit range `[low, high)` of the value that the limb holds.
/// With `gutter` set, a trailing ASCII column is added. Zero has no limbs, so it
/// renders as a header and a note rather than an empty table.
///
/// ```
/// use bigu::{audit::dump, BigU};
/// let text = dump::limb_table(&BigU::from(0x41u32), true);
/// assert!(text.contains("0x00000041"));
/// assert!(text.contains("...A"));
/// assert_eq!(text.lines().count(), 3); // header, column names, one limb
/// assert_eq!(dump::limb_table(&BigU::zero(), false).lines().count(), 2);
/// ```
pub fn limb_table(v: &BigU, gutter: bool) -> String {
    let n = layout::limb_count(v);
    let bits = v.bit_len();
    let mut out = format!(
        "BigU: {n} {}, {bits} {}\n",
        plural(n as u64, "limb"),
        plural(bits, "bit")
    );
    if n == 0 {
        out.push_str("  (no limbs: canonical zero)\n");
        return out;
    }
    out.push_str("  idx  limb        bits");
    out.push_str(if gutter { "              ascii\n" } else { "\n" });
    for (index, limb) in layout::limbs_high_to_low(v) {
        let (low, high) = layout::limb_bit_range(index);
        out.push_str(&format!("  {index:>3}  0x{limb:08x}  [{low:>5},{high:>5})"));
        if gutter {
            out.push_str(&format!("  {}", ascii_cell(limb)));
        }
        out.push('\n');
    }
    out
}

/// Renders two values in parallel columns, one row per limb index, flagging the
/// rows where they disagree.
///
/// The shorter value is padded with the zero limbs it conceptually has, so the
/// rows always line up and a length difference shows as a run of zeros on one
/// side rather than as a ragged table.
///
/// ```
/// use bigu::{audit::dump, BigU};
/// let text = dump::side_by_side(&BigU::from(1u32), &BigU::from(3u32));
/// assert!(text.contains("differs"));
/// assert!(!dump::side_by_side(&BigU::from(5u32), &BigU::from(5u32)).contains("differs"));
/// ```
pub fn side_by_side(a: &BigU, b: &BigU) -> String {
    let (left, right) = (layout::limbs(a), layout::limbs(b));
    let rows = left.len().max(right.len());
    let mut out = format!(
        "left: {} {}    right: {} {}\n",
        left.len(),
        plural(left.len() as u64, "limb"),
        right.len(),
        plural(right.len() as u64, "limb")
    );
    if rows == 0 {
        out.push_str("  (both values are zero)\n");
        return out;
    }
    out.push_str("  idx  left        right\n");
    for index in (0..rows).rev() {
        let l = left.get(index).copied().unwrap_or(0);
        let r = right.get(index).copied().unwrap_or(0);
        let mark = if l == r { "" } else { "  <- differs" };
        out.push_str(&format!("  {index:>3}  0x{l:08x}  0x{r:08x}{mark}\n"));
    }
    out
}

/// Picks the singular or plural form of `word` for `count`.
fn plural(count: u64, word: &str) -> String {
    if count == 1 {
        word.to_string()
    } else {
        format!("{word}s")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_two_limb_value_prints_high_limb_first() {
        let text = limb_table(&BigU::from(0x2_0000_0001u64), false);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 4);
        assert!(lines[0].starts_with("BigU: 2 limbs, 34 bits"));
        assert!(lines[2].contains("  1  0x00000002"));
        assert!(lines[2].contains("[   32,   64)"));
        assert!(lines[3].contains("  0  0x00000001"));
        assert!(lines[3].contains("[    0,   32)"));
    }

    #[test]
    fn the_gutter_is_optional_and_only_adds_a_column() {
        let bare = limb_table(&BigU::from(0x4142_4344u32), false);
        let with = limb_table(&BigU::from(0x4142_4344u32), true);
        assert!(!bare.contains("ABCD"));
        assert!(with.contains("ABCD"));
        assert_eq!(bare.lines().count(), with.lines().count());
    }

    #[test]
    fn unprintable_bytes_become_dots() {
        assert_eq!(ascii_cell(0x00FF_207e), ".. ~");
        assert_eq!(ascii_cell(0x2020_2020), "    ");
    }

    #[test]
    fn zero_says_so_instead_of_printing_nothing() {
        let text = limb_table(&BigU::zero(), true);
        assert!(text.contains("canonical zero"));
        assert!(!text.contains("0x"));
    }

    #[test]
    fn side_by_side_pads_the_shorter_value() {
        let text = side_by_side(&BigU::from(1u32), &BigU::from(1u64 << 40));
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 4); // header, columns, two limb rows
        assert!(lines[2].contains("0x00000000  0x00000100"));
        assert!(lines[2].contains("differs"));
        assert!(lines[3].contains("0x00000001  0x00000000"));
    }

    #[test]
    fn two_zeros_are_reported_as_a_pair_not_a_table() {
        let text = side_by_side(&BigU::zero(), &BigU::zero());
        assert!(text.contains("both values are zero"));
        assert!(!text.contains("differs"));
    }
}
