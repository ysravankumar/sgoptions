import re
from colorama import Fore, Style 
import datetime
from pytz import timezone



def parse_sg_option_call_claude(text):
    """
    Parse option call from text
    
    Handles formats:
    - BUY SYMBOL STRIKE CE/PE PRICE-PRICE
    - SYMBOL STRIKECE/PE
    - Various entry price formats
    """
    text_upper = text.upper()
    
    parsed = {
        "symbol": None,
        "strike": None,
        "type": None,
        "entry_min": None,
        "entry_max": None,
        "target": None,
        "stoploss": None
    }
    
    # Pattern 1: BUY/SELL SYMBOL STRIKE CE/PE
    main_pattern = r'(?:BUY|SELL)\s+([A-Z][\w&]+)\s+(\d+)\s+(CE|PE)'
    match = re.search(main_pattern, text_upper)
    
    if match:
        parsed['symbol'] = match.group(1).replace(' ', '')
        parsed['strike'] = int(match.group(2))
        parsed['type'] = match.group(3)
        
        # Try to extract price after CE/PE
        price_after = text_upper[match.end():]
        price_match = re.search(r'([\d.]+)\s*-\s*([\d.]+)', price_after)
        if price_match:
            parsed['entry_min'] = float(price_match.group(1))
            parsed['entry_max'] = float(price_match.group(2))
        else:
            # Single price
            single_price = re.search(r'(?:ABOVE|AT|@)?\s*([\d.]+)', price_after)
            if single_price:
                try:
                    price = float(single_price.group(1))
                    if price < 500:  # Sanity check for entry price
                        parsed['entry_min'] = price
                        parsed['entry_max'] = price
                except:
                    pass
    else:
        # Pattern 2: SYMBOL STRIKECE/PE (compact format)
        compact_pattern = r'([A-Z][\w&\s]+?)\s+(\d+)\s*(CE|PE)'
        matches = list(re.finditer(compact_pattern, text_upper))
        
        if matches:
            # Take the last match (most likely the actual call)
            match = matches[-1]
            raw_symbol = match.group(1).strip()
            
            # Clean noise words from symbol
            words = raw_symbol.split()
            noise_words = {'INTRADAY', 'BTST', 'HOLDING', 'RESULT', 'BET', 
                          'HIGH', 'RISK', 'TWO', 'DAYS', 'ADVANCE', 'FRESH',
                          'BUY', 'SELL', 'AGAIN', 'LEVELS'}
            clean_words = [w for w in words if w not in noise_words]
            
            if clean_words:
                parsed['symbol'] = ''.join(clean_words)
                parsed['strike'] = int(match.group(2))
                parsed['type'] = match.group(3)
    
    # Extract Stop Loss
    sl_pattern = r'(?:SL|STOP\s*LOSS)[\s:]*(\d+(?:\.\d+)?)'
    sl_match = re.search(sl_pattern, text_upper)
    if sl_match:
        parsed['stoploss'] = float(sl_match.group(1))
    
    # Extract Target (first value)
    target_pattern = r'(?:TGT|TTT|TARGET)[\s:]*(\d+(?:\.\d+)?)'
    target_match = re.search(target_pattern, text_upper)
    if target_match:
        parsed['target'] = float(target_match.group(1))
    
    # Extract Entry Price if not found yet
    if parsed['entry_min'] is None:
        # Pattern: AT price-price or @ price-price
        at_pattern = r'(?:AT|@)\s+(\d+(?:\.\d+)?)\s*(?:-|TO)\s*(\d+(?:\.\d+)?)'
        at_match = re.search(at_pattern, text_upper)
        if at_match:
            parsed['entry_min'] = float(at_match.group(1))
            parsed['entry_max'] = float(at_match.group(2))
        else:
            # Single price with AT
            single_at = re.search(r'(?:AT|@)\s+(\d+(?:\.\d+)?)', text_upper)
            if single_at:
                try:
                    price = float(single_at.group(1))
                    if price < 500:
                        parsed['entry_min'] = price
                        parsed['entry_max'] = price
                except:
                    pass
    
    # If still no entry price, look for any price range in text
    if parsed['entry_min'] is None and parsed['symbol']:
        # Avoid matching strike or SL/TGT values
        all_numbers = re.findall(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', text)
        for num1, num2 in all_numbers:
            try:
                min_val = float(num1)
                max_val = float(num2)
                # Entry prices are usually < 500 and not the strike
                if min_val < 500 and max_val < 500 and min_val != parsed['strike']:
                    parsed['entry_min'] = min_val
                    parsed['entry_max'] = max_val
                    break
            except:
                continue
    
    return parsed

#-------------------------------------

def expand_range(value):
    """Expand shortened ranges like 110-13 to 110-113"""
    if '-' not in value:
        return value
    parts = value.split('-')
    if len(parts) != 2:
        return value
    start, end = parts[0].strip(), parts[1].strip()
    if not (start.replace('.', '').isdigit() and end.replace('.', '').isdigit()):
        return value
    start_int = start.split('.')[0]
    end_int = end.split('.')[0] if '.' in end else end
    if len(end_int) < len(start_int):
        prefix = start_int[:len(start_int) - len(end_int)]
        expanded_end = prefix + end if '.' not in end else prefix + end
        return f"{start}-{expanded_end}"
    return value

def parse_sg_opt_msgs_enhanced(msg: str):

    isAbove = 'above' in msg.lower()
    msg = msg.lower().replace("only", "").replace("again", "").replace("above", "\nat").upper()
    lines = list(filter(None, msg.strip().split('\n'))) 
    msg_dict = {}
    parse_msg = ""
    ignore_words = ['BOOK', 'PROFIT', 'ACHIEVED', 'STBT', 'SELL', 'WATCHLIST']
    #check ignore_words in msg
    if any(word in msg.upper() for word in ignore_words):
        print(Fore.RED + f"ignoring for {ignore_words}")
        print(Style.RESET_ALL)
        return parse_msg, isAbove
    
    msg_dict['Action'] = 'BUY'    

    for line in lines:
        line = line.strip()
        if not line:
            continue  # Skip empty lines
        
        # Check for Actions (e.g., INTRADAY, BTST, HOLDING, INTRA)
        #ignore line if any word in the ignore_words 
        firstline_words = ['INTRADAY', 'BTST', 'HOLDING', 'INTRA', 'RESULT BET', 'TWO DAYS HOLDING', 'AGAIN']
        if any(word in line.upper() for word in firstline_words):
            continue
        
        # Check for Instrument details
        # Example: TRENT 7200CE, PERSISTENT 5600CE, etc.
        instrument_pattern = re.compile(r'^(BUY\s+)?([A-Z\s]+?\d+(CE|PE))$', re.IGNORECASE)
        match = instrument_pattern.match(line)
        if match:
            # Extract instrument name                
            instrument = match.group(2).strip().upper()
            opt_match = re.search(r"(CE|PE)$", instrument)
            if opt_match:
                instrument = instrument.replace(opt_match.group(1), " "+opt_match.group(1))
            msg_dict['Instrument'] = instrument
            continue
        
        # Alternative pattern for instruments like "BUY ADANIENT 3000 CE 89-91"
        instrument_pattern_alt = re.compile(r'^(BUY\s+)?([A-Z\s]+?\d+ (CE|PE))\s+([\d\.\-+*\/]+)$', re.IGNORECASE)
        match_alt = instrument_pattern_alt.match(line)
        if match_alt:
            instrument = match_alt.group(2).strip().upper()
            opt_match = re.search(r"(CE|PE)$", instrument)
            if opt_match:
                instrument = instrument.replace(opt_match.group(1), " "+opt_match.group(1))
            msg_dict['Instrument'] = instrument
            # Capture AT value if present
            at_value = match_alt.group(4).strip()
            at_value = re.sub(r'(?<=\d)[^.\d]+(?=\d)', '-', at_value)
            at_value = re.sub(r'[^\d.-]+$', '', at_value)
            at_value = expand_range(at_value)
            msg_dict['AT'] = at_value
            continue
        
        # Check for Entry Point (AT)
        if line.upper().startswith('AT'):
            at_value = line[2:].strip()
            at_value = re.sub(r'(?<=\d)[^.\d]+(?=\d)', '-', at_value)
            at_value = re.sub(r'[^\d.-]+$', '', at_value)
            at_value = expand_range(at_value)
            msg_dict['AT'] = at_value
            continue
        
        # Check for Stop Loss (SL)
        if line.upper().startswith('SL'):
            sl_value = line[2:].strip()
            try:
                msg_dict['SL'] = float(sl_value)
            except ValueError:
                msg_dict['SL'] = sl_value  # Keep as string if not a number
            #continue
            break #no need of further parse
        
        # Check for Target (TGT)
        # if line.upper().startswith('TGT'):
        #     tgt_values = line[3:].strip()
        #     msg_dict['TGT'] = tgt_values
        #     continue
    
    return msg_dict, isAbove

#-----------------------------------------
def parse_sg_opt_msgs_enhanced_new(msg):
    isAbove = 'above' in msg.lower()
    msg_upper = msg.upper().replace("AGAIN", " ")
    if any(x in msg_upper for x in ['BOOK', 'PROFIT', 'SELL', 'WATCHLIST']):
        return "", isAbove
    
    symbol = None
    price = None
    sl = None

    
    lines = msg.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Extract instrument
        if not symbol:
            # Pattern 1: "BUY SYMBOL STRIKE CE/PE price"
            match = re.search(r'BUY\s+([A-Z]+(?:\s+[A-Z]+)*)\s+(\d+)\s+(CE|PE)\s+([\d.-]+)', line.upper())
            if match:
                symbol = f"{match.group(1).strip()} {match.group(2)} {match.group(3)}"
                price = match.group(4)
                continue
            
            # Pattern 2: "BUY SYMBOL STRIKE CE/PE" with "above" or "abov" price
            match = re.search(r'BUY\s+([A-Z]+(?:\s+[A-Z]+)*)\s+(\d+)\s+(CE|PE)', line.upper())
            if match:
                symbol = f"{match.group(1).strip()} {match.group(2)} {match.group(3)}"
                if 'above' in line.lower() or 'abov' in line.lower():
                    price_match = re.search(r'(?:above?|abov)\s+([\d.-]+)', line, re.I)
                    if price_match:
                        price = price_match.group(1)
                continue
            
            # Pattern 3: Compact format "SYMBOLSTRIKECE" or "SYMBOL WORD STRIKECE"
            if re.search(r'[A-Z]+(?:\s+[A-Z]+)*\s*\d+(CE|PE)$', line.upper()):
                match = re.search(r'([A-Z]+(?:\s+[A-Z]+)*)\s*(\d+)(CE|PE)', line.upper())
                if match:
                    symbol = f"{match.group(1).strip()} {match.group(2)} {match.group(3)}"
                    continue
        
        # Extract price from AT line
        if not price and line.upper().startswith('AT'):
            match = re.search(r'AT\s*([\d.-]+)', line.upper())
            if match:
                price = match.group(1).replace('+', '')
        
        # Extract SL
        if line.upper().startswith('SL'):
            match = re.search(r'SL\s*([\d.]+)', line.upper())
            if match:
                sl = match.group(1)
    
    print(f"Parsed values - Symbol: {symbol}, Price: {price}, SL: {sl}")
    if symbol and price and sl:
        return{
            'Action': 'BUY',
            'Instrument': symbol,
            'AT': price,
            'SL': sl
        }, isAbove
            
    return {}, isAbove



def parse_option_symbol(s):
    print(f"Parsing option symbol from: {s}")
    pattern = r"^([A-Z&]+)(\d+(?:\.\d+)?)(CE|PE)$"
    #r"^([A-Z]+)(\d+(?:\.\d+)?)(CE|PE)$"
    match = re.match(pattern, s)
    if match:
        return {
            'symbol': match.group(1),
            'strike': int(match.group(2)),
            'type': match.group(3)
        }
    return None

def parse_at_price(s):
    print(f"Parsing AT price from: {s}")
    entry_min = s
    entry_max = s
    if ('-' in s):
        entry_list = re.findall(r"\d*\.\d+|\d+", s)
        entry_min = str(entry_list[0])
        entry_max = str(entry_list[-1])
    print(f"Parsed AT price - Min: {entry_min}, Max: {entry_max}")
    return entry_min, entry_max
    


def parse_sg_opt_msgs(msg):
    parsed = ""
    isAbove = False
    ret_dic = {}
    try:
        parsed = parse_sg_option_call_claude(msg)
        print(f"------>parse_sg_option_call_claude returned: {parsed}")
    except Exception as e:
        print(f"parse_sg_option_call_claude Error parsing message: {e}")
    try:
        parsed, isAbove = parse_sg_opt_msgs_enhanced(msg)
        print(f"parse_sg_opt_msgs_enhanced returned: {parsed}, isAbove: {isAbove}")
        if parsed.get('Instrument') and parsed.get('AT') and parsed.get('SL'):
            sym_str_opt = parse_option_symbol(parsed['Instrument'].replace(" ", ""))
            print(f"Parsed symbol details: {sym_str_opt}")
            if sym_str_opt:
                ret_dic['symbol'] = sym_str_opt['symbol']
                ret_dic['strike'] = sym_str_opt['strike']
                ret_dic['type'] = sym_str_opt['type']
                ret_dic['entry_min'], ret_dic['entry_max'] = parse_at_price(parsed['AT'])
                ret_dic['stoploss'] = parsed['SL']
                ret_dic['entry'] = ret_dic['entry_max']
                return ret_dic, isAbove        
    except Exception as e:
        print(f"parse_sg_opt_msgs_enhanced Error parsing message: {e}")

    print("trying with enhanced")
    try:
        parsed, isAbove = parse_sg_opt_msgs_enhanced_new(msg)
        print(f"parse_sg_opt_msgs_enhanced_new returned: {parsed}, isAbove: {isAbove}")
        if parsed.get('Instrument') and parsed.get('AT') and parsed.get('SL'):
            sym_str_opt = parse_option_symbol(parsed['Instrument'].replace(" ", ""))
            print(f"Parsed symbol details: {sym_str_opt}")
            if sym_str_opt:
                ret_dic['symbol'] = sym_str_opt['symbol']
                ret_dic['strike'] = sym_str_opt['strike']
                ret_dic['type'] = sym_str_opt['type']
                ret_dic['entry_min'], ret_dic['entry_max'] = parse_at_price(parsed['AT'])
                ret_dic['stoploss'] = parsed['SL']
                ret_dic['entry'] = ret_dic['entry_max']
                return ret_dic, isAbove        
    except Exception as e:
        print(f"parse_sg_opt_msgs_enhanced_new Error parsing message: {e}")
    
    return ret_dic, isAbove

