# Ki2DICE

## What is Ki2DICE?
Ki2DICE is a small python helper program to make development of games for DICE much easier. Ki2DICE allows circuits to be constructed from the 74xx KiCAD library and the included DICE KiCAD library, then be translated into the appropriate DICE-compatible C++ source file format to be used. Parts from other libraries can be added to dice_parts.json to add compatibility for translation. 

## Including the DICE Library in KiCAD
To make sure that DICE.kicad_sym is included in your project, first select From Preferences -> Symbol Libraries from the Project Files window. Under Global Libraries, click the "+", nickname the new entry "DICE". Then, direct the Library Path to the .kicad_sym file. Ensure the Library Format is set to KiCAD. The library should now be available in the KiCAD Schematic editor in the form of signal inputs, video output, and helper symbols. 

## How to add parts to the converter
Old designs use lots of archaic chips, which will warrant new symbols in KiCAD.  These new symbols can be added to dice_parts.json to add compatibility for translation. Symbols can utilize extra fields to define variables, such as time constants, resistances, or periods, to give DICE extra information on how to model things.

It should be noted that the pins on the KiCAD symbol will be utilized exactly as they are for the translation. In special cases, pins are named oddly because of this: take JOYSTICK1_INPUT and its Joystick::UP pins. Most pins should stick to the typical numbers.

There are two base containers in the dice_parts JSON file: one for rail voltage synonyms, and one for the parts (or chips). The parts container contains containers for each of the DICE chips named as they are in the source code. Within each, there are key-value pairs to describe .
If there are no extra parameters, a "type" key with a value consisting of the KiCAD symbol's name will suffice. 
If there are parameters, a "desc" key with the value consisting of the code to be inserted into the C++ file is also declared. KiCAD symbol fields are accessed with the syntax ${FIELDNAME}.

The VIDEO chip is a special case, and requires some special declaration, that will be covered but not used. DICE requires the VIDEO symbol to be named VIDEO, but KiCAD wants to annotate the schematic so that each symbol ends in a number. This is dealt with using the special key of "name". "chip" is used in the CIRCUIT_LAYOUT declaration in the C++ file, as VIDEO isn't treated the same as a chip and has a special declaration there too.



