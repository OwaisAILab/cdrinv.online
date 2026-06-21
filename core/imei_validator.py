def calculate_luhn_check_digit(imei14: str) -> str:
    """
    Calculate GSM IMEI check digit using Luhn algorithm.
    Input must be first 14 digits.
    """
    digits = [int(d) for d in imei14]
    total = 0

    # Luhn from right to left
    for i in range(len(digits) - 1, -1, -1):
        d = digits[i]
        if (len(digits) - i) % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d

    return str((10 - (total % 10)) % 10)


def validate_imei(imei: str) -> dict:
    """
    Returns:
        {
            "original": str,
            "is_valid": bool,
            "is_zero_padded": bool,
            "correct_check_digit": str,
            "corrected_imei": str
        }
    """
    imei = str(imei).strip()

    if not imei.isdigit() or len(imei) != 15:
        return {
            "original": imei,
            "is_valid": False,
            "is_zero_padded": False,
            "correct_check_digit": "",
            "corrected_imei": ""
        }

    imei14 = imei[:14]
    provided_check = imei[-1]

    expected_check = calculate_luhn_check_digit(imei14)

    is_valid = provided_check == expected_check
    is_zero_padded = provided_check == "0"

    corrected = imei14 + expected_check

    return {
        "original": imei,
        "is_valid": is_valid,
        "is_zero_padded": is_zero_padded,
        "correct_check_digit": expected_check,
        "corrected_imei": corrected
    }