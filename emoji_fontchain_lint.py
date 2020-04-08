from os import path
import collections
import sys
import copy
from fontTools import ttLib


_script_to_font_map = collections.defaultdict(set)
_fallback_chains = {}
_all_fonts = []

EMOJI_VS = 0xFE0F
SAME_FLAG_MAPPINGS = [
    # Diego Garcia and British Indian Ocean Territory
    ((0x1F1EE, 0x1F1F4), (0x1F1E9, 0x1F1EC)),
    # St. Martin and France
    ((0x1F1F2, 0x1F1EB), (0x1F1EB, 0x1F1F7)),
    # Spain and Ceuta & Melilla
    ((0x1F1EA, 0x1F1F8), (0x1F1EA, 0x1F1E6)),
]


def flag_sequence(territory_code):
    return tuple(0x1F1E6 + ord(ch) - ord('A') for ch in territory_code)


COMBINING_KEYCAP = 0x20E3
LEGACY_ANDROID_EMOJI = {
    0xFE4E5: flag_sequence('JP'),
    0xFE4E6: flag_sequence('US'),
    0xFE4E7: flag_sequence('FR'),
    0xFE4E8: flag_sequence('DE'),
    0xFE4E9: flag_sequence('IT'),
    0xFE4EA: flag_sequence('GB'),
    0xFE4EB: flag_sequence('ES'),
    0xFE4EC: flag_sequence('RU'),
    0xFE4ED: flag_sequence('CN'),
    0xFE4EE: flag_sequence('KR'),
    0xFE82C: (ord('#'), COMBINING_KEYCAP),
    0xFE82E: (ord('1'), COMBINING_KEYCAP),
    0xFE82F: (ord('2'), COMBINING_KEYCAP),
    0xFE830: (ord('3'), COMBINING_KEYCAP),
    0xFE831: (ord('4'), COMBINING_KEYCAP),
    0xFE832: (ord('5'), COMBINING_KEYCAP),
    0xFE833: (ord('6'), COMBINING_KEYCAP),
    0xFE834: (ord('7'), COMBINING_KEYCAP),
    0xFE835: (ord('8'), COMBINING_KEYCAP),
    0xFE836: (ord('9'), COMBINING_KEYCAP),
    0xFE837: (ord('0'), COMBINING_KEYCAP),
}
EQUIVALENT_FLAGS = {
    flag_sequence('BV'): flag_sequence('NO'),
    flag_sequence('CP'): flag_sequence('FR'),
    flag_sequence('HM'): flag_sequence('AU'),
    flag_sequence('SJ'): flag_sequence('NO'),
    flag_sequence('UM'): flag_sequence('US'),
}
ZWJ_IDENTICALS = {
}


def parse_unicode_datafile(file_path, reverse=False):
    if reverse:
        output_dict = collections.defaultdict(set)
    else:
        output_dict = {}
    with open(file_path) as datafile:
        for line in datafile:
            if '#' in line:
                line = line[:line.index('#')]
            line = line.strip()
            if not line:
                continue
            chars, prop = line.split(';')[:2]
            chars = chars.strip()
            prop = prop.strip()
            if ' ' in chars:  # character sequence
                sequence = [int(ch, 16) for ch in chars.split(' ')]
                additions = [tuple(sequence)]
            elif '..' in chars:  # character range
                char_start, char_end = chars.split('..')
                char_start = int(char_start, 16)
                char_end = int(char_end, 16)
                additions = range(char_start, char_end+1)
            else:  # singe character
                additions = [int(chars, 16)]
            if reverse:
                output_dict[prop].update(additions)
            else:
                for addition in additions:
                    assert addition not in output_dict
                    output_dict[addition] = prop
    return output_dict


def parse_emoji_variants(file_path):
    emoji_set = set()
    text_set = set()
    with open(file_path) as datafile:
        for line in datafile:
            if '#' in line:
                line = line[:line.index('#')]
            line = line.strip()
            if not line:
                continue
            sequence, description, _ = line.split(';')
            sequence = sequence.strip().split(' ')
            base = int(sequence[0], 16)
            vs = int(sequence[1], 16)
            description = description.strip()
            if description == 'text style':
                text_set.add((base, vs))
            elif description == 'emoji style':
                emoji_set.add((base, vs))
    return text_set, emoji_set


def remove_emoji_exclude(source, items):
    return {k: v for k, v in source.items() if k not in items}


def remove_emoji_variation_exclude(source, items):
    return source.difference(items.keys())


def parse_ucd(ucd_path):
    global _emoji_properties, _chars_by_age
    global _text_variation_sequences, _emoji_variation_sequences
    global _emoji_sequences, _emoji_zwj_sequences
    _emoji_properties = parse_unicode_datafile(
        path.join(ucd_path, 'emoji-data.txt'), reverse=True)
    emoji_properties_additions = parse_unicode_datafile(
        path.join(ucd_path, 'additions', 'emoji-data.txt'), reverse=True)
    for prop in emoji_properties_additions.keys():
        _emoji_properties[prop].update(emoji_properties_additions[prop])
    _chars_by_age = parse_unicode_datafile(
        path.join(ucd_path, 'DerivedAge.txt'), reverse=True)
    sequences = parse_emoji_variants(
        path.join(ucd_path, 'emoji-variation-sequences.txt'))
    _text_variation_sequences, _emoji_variation_sequences = sequences
    _emoji_sequences = parse_unicode_datafile(
        path.join(ucd_path, 'emoji-sequences.txt'))
    _emoji_sequences.update(parse_unicode_datafile(
        path.join(ucd_path, 'additions', 'emoji-sequences.txt')))
    _emoji_zwj_sequences = parse_unicode_datafile(
        path.join(ucd_path, 'emoji-zwj-sequences.txt'))
    _emoji_zwj_sequences.update(parse_unicode_datafile(
        path.join(ucd_path, 'additions', 'emoji-zwj-sequences.txt')))
    exclusions = parse_unicode_datafile(path.join(ucd_path, 'additions', 'emoji-exclusions.txt'))
    _emoji_sequences = remove_emoji_exclude(_emoji_sequences, exclusions)
    _emoji_zwj_sequences = remove_emoji_exclude(_emoji_zwj_sequences, exclusions)
    _emoji_variation_sequences = remove_emoji_variation_exclude(_emoji_variation_sequences, exclusions)
    # Unicode 12.0 adds Basic_Emoji in emoji-sequences.txt. We ignore them here since we are already
    # checking the emoji presentations with emoji-variation-sequences.txt.
    # Please refer to http://unicode.org/reports/tr51/#def_basic_emoji_set .
    _emoji_sequences = {k: v for k, v in _emoji_sequences.items() if not v == 'Basic_Emoji' }


def is_fitzpatrick_modifier(cp):
    return 0x1F3FB <= cp <= 0x1F3FF


def reverse_emoji(seq):
    rev = list(reversed(seq))
    # if there are fitzpatrick modifiers in the sequence, keep them after
    # the emoji they modify
    for i in range(1, len(rev)):
        if is_fitzpatrick_modifier(rev[i-1]):
            rev[i], rev[i-1] = rev[i-1], rev[i]
    return tuple(rev)


def compute_expected_emoji():
    equivalent_emoji = {}
    sequence_pieces = set()
    all_sequences = set()
    all_sequences.update(_emoji_variation_sequences)
    # add zwj sequences not in the current emoji-zwj-sequences.txt
    adjusted_emoji_zwj_sequences = dict(_emoji_zwj_sequences)
    adjusted_emoji_zwj_sequences.update(_emoji_zwj_sequences)
    # Add empty flag tag sequence that is supported as fallback
    _emoji_sequences[(0x1F3F4, 0xE007F)] = 'Emoji_Tag_Sequence'
    for sequence in _emoji_sequences.keys():
        sequence = tuple(ch for ch in sequence if ch != EMOJI_VS)
        all_sequences.add(sequence)
        sequence_pieces.update(sequence)
        if _emoji_sequences.get(sequence, None) == 'Emoji_Tag_Sequence':
            # Add reverse of all emoji ZWJ sequences, which are added to the
            # fonts as a workaround to get the sequences work in RTL text.
            # TODO: test if these are actually needed by Minikin/HarfBuzz.
            reversed_seq = reverse_emoji(sequence)
            all_sequences.add(reversed_seq)
            equivalent_emoji[reversed_seq] = sequence
    for sequence in adjusted_emoji_zwj_sequences.keys():
        sequence = tuple(ch for ch in sequence if ch != EMOJI_VS)
        all_sequences.add(sequence)
        sequence_pieces.update(sequence)
        # Add reverse of all emoji ZWJ sequences, which are added to the fonts
        # as a workaround to get the sequences work in RTL text.
        reversed_seq = reverse_emoji(sequence)
        all_sequences.add(reversed_seq)
        equivalent_emoji[reversed_seq] = sequence
    for first, second in SAME_FLAG_MAPPINGS:
        equivalent_emoji[first] = second
    # Add all tag characters used in flags
    sequence_pieces.update(range(0xE0030, 0xE0039 + 1))
    sequence_pieces.update(range(0xE0061, 0xE007A + 1))
    all_emoji = (
        _emoji_properties['Emoji'] |
        all_sequences |
        sequence_pieces |
        set(LEGACY_ANDROID_EMOJI.keys()))
    default_emoji = (
        _emoji_properties['Emoji_Presentation'] |
        all_sequences |
        set(LEGACY_ANDROID_EMOJI.keys()))
    equivalent_emoji.update(EQUIVALENT_FLAGS)
    equivalent_emoji.update(LEGACY_ANDROID_EMOJI)
    equivalent_emoji.update(ZWJ_IDENTICALS)
    for seq in _emoji_variation_sequences:
        equivalent_emoji[seq] = seq[0]
    return all_emoji, default_emoji, equivalent_emoji


def get_emoji_font():
    return "./fonts/NotoColorEmoji.ttf"


def open_font(font):

    font_file, index = "NotoColorEmoji.ttf", 0
    font_path = path.join("./fonts", font_file)
    if index is not None:
        return ttLib.TTFont(font_path, fontNumber=index)
    else:
        return ttLib.TTFont(font_path)


def get_best_cmap(font):
    ttfont = open_font(font)
    all_unicode_cmap = None
    bmp_cmap = None
    for cmap in ttfont['cmap'].tables:
        specifier = (cmap.format, cmap.platformID, cmap.platEncID)
        if specifier == (4, 3, 1):
            assert bmp_cmap is None, 'More than one BMP cmap in %s' % (font, )
            bmp_cmap = cmap
        elif specifier == (12, 3, 10):
            assert all_unicode_cmap is None, (
                'More than one UCS-4 cmap in %s' % (font, ))
            all_unicode_cmap = cmap
    return all_unicode_cmap.cmap if all_unicode_cmap else bmp_cmap.cmap


def get_variation_sequences_cmap(font):
    ttfont = open_font(font)
    vs_cmap = None
    for cmap in ttfont['cmap'].tables:
        specifier = (cmap.format, cmap.platformID, cmap.platEncID)
        if specifier == (14, 0, 5):
            assert vs_cmap is None, 'More than one VS cmap in %s' % (font, )
            vs_cmap = cmap
    return vs_cmap


def get_emoji_map(font):
    # Add normal characters
    emoji_map = copy.copy(get_best_cmap(font))
    reverse_cmap = {glyph: code for code, glyph in emoji_map.items()}
    # Add variation sequences
    vs_dict = get_variation_sequences_cmap(font).uvsDict
    for vs in vs_dict:
        for base, glyph in vs_dict[vs]:
            if glyph is None:
                emoji_map[(base, vs)] = emoji_map[base]
            else:
                emoji_map[(base, vs)] = glyph
    # Add GSUB rules
    ttfont = open_font(font)
    for lookup in ttfont['GSUB'].table.LookupList.Lookup:
        if lookup.LookupType != 4:
            # Other lookups are used in the emoji font for fallback.
            # We ignore them for now.
            continue
        for subtable in lookup.SubTable:
            ligatures = subtable.ligatures
            for first_glyph in ligatures:
                for ligature in ligatures[first_glyph]:
                    sequence = [first_glyph] + ligature.Component
                    sequence = [reverse_cmap[glyph] for glyph in sequence]
                    sequence = tuple(sequence)
                    # Make sure no starting subsequence of 'sequence' has been
                    # seen before.
                    for sub_len in range(2, len(sequence)+1):
                        subsequence = sequence[:sub_len]
                        assert subsequence not in emoji_map
                    emoji_map[sequence] = ligature.LigGlyph
    print(emoji_map)
    return emoji_map


def printable(inp):
    if type(inp) is set:  # set of character sequences
        return '{' + ', '.join([printable(seq) for seq in inp]) + '}'
    if type(inp) is tuple:  # character sequence
        return '<' + (', '.join([printable(ch) for ch in inp])) + '>'
    else:  # single character
        return 'U+%04X' % inp


def check_emoji_font_coverage(emoji_font, all_emoji, equivalent_emoji):
    coverage = get_emoji_map(emoji_font)
    for sequence in all_emoji:
        assert sequence in coverage, (
            '%s is not supported in the emoji font.' % printable(sequence))
    for sequence in coverage:
        if sequence in {0x0000, 0x000D, 0x0020}:
            # The font needs to support a few extra characters, which is OK
            continue
        assert sequence in all_emoji, (
            'Emoji font should not support %s.' % printable(sequence))
    for first, second in equivalent_emoji.items():
        assert coverage[first] == coverage[second], (
            '%s and %s should map to the same glyph.' % (
                printable(first),
                printable(second)))
    for glyph in set(coverage.values()):
        maps_to_glyph = [seq for seq in coverage if coverage[seq] == glyph]
        if len(maps_to_glyph) > 1:
            # There are more than one sequences mapping to the same glyph. We
            # need to make sure they were expected to be equivalent.
            equivalent_seqs = set()
            for seq in maps_to_glyph:
                equivalent_seq = seq
                while equivalent_seq in equivalent_emoji:
                    equivalent_seq = equivalent_emoji[equivalent_seq]
                equivalent_seqs.add(equivalent_seq)
            assert len(equivalent_seqs) == 1, (
                'The sequences %s should not result in the same glyph %s' % (
                    printable(equivalent_seqs),
                    glyph))


def check_emoji_coverage(all_emoji, equivalent_emoji):
    emoji_font = get_emoji_font()
    check_emoji_font_coverage(emoji_font, all_emoji, equivalent_emoji)


def assert_font_supports_none_of_chars(font, chars, fallbackName):
    best_cmap = get_best_cmap(font)
    for char in chars:
        if fallbackName:
            assert char not in best_cmap, 'U+%04X was found in %s' % (char, font)
        else:
            assert char not in best_cmap, (
                'U+%04X was found in %s in fallback %s' % (char, font, fallbackName))


def check_emoji_defaults(default_emoji):
    missing_text_chars = _emoji_properties['Emoji'] - default_emoji
    for name, fallback_chain in _fallback_chains.items():
        emoji_font_seen = False
        for record in fallback_chain:
            if 'Zsye' in record.scripts:
                emoji_font_seen = True
                # No need to check the emoji font
                continue
            # For later fonts, we only check them if they have a script
            # defined, since the defined script may get them to a higher
            # score even if they appear after the emoji font. However,
            # we should skip checking the text symbols font, since
            # symbol fonts should be able to override the emoji display
            # style when 'Zsym' is explicitly specified by the user.
            if emoji_font_seen and (not record.scripts or 'Zsym' in record.scripts):
                continue
            # Check default emoji-style characters
            assert_font_supports_none_of_chars(record.font, default_emoji, name)
            # Mark default text-style characters appearing in fonts above the emoji
            # font as seen
            if not emoji_font_seen:
                missing_text_chars -= set(get_best_cmap(record.font))
        # Noto does not have monochrome glyphs for Unicode 7.0 wingdings and
        # webdings yet.
        missing_text_chars -= _chars_by_age['7.0']
        assert missing_text_chars == set(), (
            'Text style version of some emoji characters are missing: ' +
            repr(missing_text_chars)
        )


def main():
    ucd_path = "./ucd"
    parse_ucd(ucd_path)

    # Generate all expected emoji
    all_emoji, default_emoji, equivalent_emoji = compute_expected_emoji()
    print(all_emoji)

    check_emoji_coverage(all_emoji, equivalent_emoji)
    # check_emoji_defaults(default_emoji)


if __name__ == '__main__':
    main()
