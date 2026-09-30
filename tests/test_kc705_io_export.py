"""Electrical export guards: exact external-VREF correction and ECC bit masking."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
from kc705_fix_external_vref import corrected_fasm
from kc705_export_bitstream import frame_data_word


class IOExportTest(unittest.TestCase):
    tiles = ["HCLK_IOI_X235Y26", "HCLK_IOI_X235Y130"]

    def test_only_internal_vref_features_removed(self):
        source = "IOB.SSTL15.IN\n" + "\n".join(t+".VREF.V_675_MV" for t in self.tiles) + "\nBRAM.INIT[31:0] = 32'hdeadbeef\n"
        corrected, removed = corrected_fasm(source, self.tiles)
        self.assertEqual(corrected, "IOB.SSTL15.IN\nBRAM.INIT[31:0] = 32'hdeadbeef\n")
        self.assertEqual(len(removed), 2)

    def test_unexpected_voltage_or_bank_rejected(self):
        for features in [[], [self.tiles[0]+".VREF.V_675_MV"],
                         [t+".VREF.V_750_MV" for t in self.tiles],
                         [t+".VREF.V_675_MV" for t in self.tiles]+["HCLK_IOI_X235Y78.VREF.V_675_MV"]]:
            with self.assertRaises(ValueError):
                corrected_fasm("\n".join(features), self.tiles)

    def test_ecc_bits_are_excluded(self):
        self.assertEqual(frame_data_word(50, 0x1fff), 0)
        self.assertEqual(frame_data_word(49, 0x1fff), 0x1fff)

    def test_upper_ecc_word_configuration_is_preserved(self):
        for bit in range(13, 32):
            self.assertEqual(frame_data_word(50, 1<<bit), 1<<bit)


if __name__ == "__main__":
    unittest.main()
