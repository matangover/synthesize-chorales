import music21
import music21.stream
import music21.note
import music21.corpus.chorales
import subprocess
import os
from pathlib import Path
import random
import copy

random.seed(1337)

soundfont = 'path/to/MuseScore_General.sf3'
base_output_dir = Path('chorales_synth')

parts_to_synthesize = ['Soprano', 'Alto', 'Tenor', 'Bass']
part_ids = {'Soprano', 'Alto', 'Tenor', 'Bass'}
parts_to_mix = ['Soprano', 'Alto', 'Tenor', 'Bass']

midi_output_dir = base_output_dir / 'midi'
stereo_audio_output_dir = base_output_dir / 'audio_stereo'
audio_output_dir = base_output_dir / 'audio_mono'
mix_output_dir = base_output_dir / 'mix'
output_dirs = [midi_output_dir, stereo_audio_output_dir, audio_output_dir, mix_output_dir]

def synthesize_all():
    for chorale in music21.corpus.chorales.Iterator():
        synthesize_chorale(chorale, chorale.metadata.number)

def synthesize_chorale(chorale, chorale_number):
    print(f'Processing chorale: {chorale_number}')
    actual_part_ids = {p.id for p in chorale.parts}
    if actual_part_ids != part_ids:
        # TODO: There are 3 chorales with .krn files alongside the .mxl, and corpus
        #       loads the .krn by default. Use ChoraleListRKBWV().byRiemenschneider.
        #       For now, patched music21/corpus/chorales.py line 1269:
        #           - chorale = corpus.parse(filename)
        #           + chorale = corpus.parse(filename, fileExtensions=['.mxl'])
        print(f'\tSkipping. part_ids: {actual_part_ids}')
        return

    file_name = f'chorale_{int(chorale_number):03}'
    synthesize_parts(chorale, file_name)
    mix_parts(file_name, parts_to_mix, mix_output_dir, audio_output_dir)

def synthesize_parts(chorale, file_name):
    # Random tempo from 70 to 100 BPM.
    tempo = 70 + random.randint(0, 6) * 5
    print(f'\tTempo: {tempo}')
    for part_id in parts_to_synthesize:
        part = chorale.parts[part_id]
        part.removeByClass('Instrument')
        part.insert(0, music21.instrument.Vocalist())
        part.insert(0, music21.tempo.MetronomeMark(number=tempo))
        synthesize(part, f'{file_name}_{part_id.lower()}')

def synthesize(stream, name):
    # TODO: Add 'expressive performance':
    #        - Slow down before fermatas (more in final phrase)
    #        - Add breath after (some?) fermatas
    #        - Make soprano a bit louder
    add_some_breaths(stream)
    drop_some_notes(stream)
    midi_file_name = str(midi_output_dir / f'{name}.mid')
    stream.write('midi', midi_file_name)

    output = stereo_audio_output_dir / f'{name}.wav'
    print(f'\tSynthesizing: {output}')
    subprocess.run(['fluidsynth', '--sample-rate=22050' '--reverb=no', '-F', output, soundfont, midi_file_name], check=True, stdout=subprocess.DEVNULL)
    output_mono = audio_output_dir / f'{name}.wav'
    subprocess.run(['sox', output, '-c', '1', output_mono], check=True, stdout=subprocess.DEVNULL)
    return output_mono

def get_part_filename(file_name, part_id, parts_dir):
    return parts_dir / f'{file_name}_{part_id.lower()}.wav'

def synthesize_single(chorale_number):
    chorale_list = music21.corpus.chorales.ChoraleListRKBWV()
    filename = 'bach/bwv' + str(chorale_list.byRiemenschneider[chorale_number]['bwv'])
    chorale = music21.corpus.parse(filename, fileExtensions=['.mxl'])
    synthesize_chorale(chorale, chorale_number)

def main():
    for output in output_dirs:
        os.makedirs(output, exist_ok=True)

    synthesize_all()

def add_some_breaths(stream: music21.stream.Stream):
    """
    Change every 8th beat into a rest. (Sorry, Bach.)
    Always leave last two beats intact.
    """
    for beat_start in range(7, int(stream.highestTime) - 2, 8):
        insert_in_measure(stream, beat_start, music21.note.Rest(quarterLength=1))
        beat_end = beat_start + 1
        notes = stream.flat.getElementsByOffset(
            beat_start, beat_end, includeEndBoundary=False, mustFinishInSpan=False, mustBeginInSpan=False,
            includeElementsThatEndAtStart=False, classList=[music21.note.Note])
        for note in notes:
            note_end = note.offset + note.quarterLength
            if note.offset < beat_start:
                note_before_beat: music21.note.Note = copy.deepcopy(note)
                note_before_beat.tie = None
                note_before_beat.quarterLength = beat_start - note.offset
                insert_in_measure(stream, note.offset, note_before_beat)
            if note_end > beat_end:
                note_after_beat: music21.note.Note = copy.deepcopy(note)
                note_after_beat.tie = None
                note_after_beat.quarterLength = note_end - beat_end
                insert_in_measure(stream, beat_end, note_after_beat)
        
            remove_neighboring_ties(note)
            stream.remove(note, recurse=True)

def insert_in_measure(stream, offset, element):
    beat, measure = stream.beatAndMeasureFromOffset(offset)
    measure_offset = beat - 1
    measure.insert(measure_offset, element)

def drop_some_notes(stream: music21.stream.Stream):
    """
    Change 10% of the notes into rests.
    Always leave last two beats intact, because if the last beat is removed FluidSynth will
    generate a shorter audio file and that causes problems when preprocessing the dataset --
    all sources must be of equal length.
    """
    flat_stream = stream.flat
    notes = list(flat_stream.notes)
    notes_to_drop = len(notes) // 10
    indices_to_remove = random.sample(range(len(notes) - 2), notes_to_drop)
    for note_index in indices_to_remove:
        note = notes[note_index]
        remove_neighboring_ties(note)
        stream.flat.replace(note, music21.note.Rest(quarterLength=note.quarterLength))

def remove_neighboring_ties(note):
    if note.tie is None:
        return
        
    if note.tie.type in ('continue', 'start'):
        previous_note = note.previous('Note')
        if previous_note and previous_note.tie is not None:
            if previous_note.tie.type == 'start':
                previous_note.tie = None
            elif previous_note.tie.type == 'continue':
                previous_note.tie.type = 'end'
    
    if note.tie.type in ('continue', 'end'):
        next_note = note.next('Note')
        if next_note and next_note.tie is not None:
            if next_note.tie.type == 'end':
                next_note.tie = None
            elif next_note.tie.type == 'continue':
                next_note.tie.type = 'start'

def mix_parts(chorale_name, parts, output_dir, parts_dir):
    # It's possible to let FluidSynth synthesize multiple voices at the same time, but in
    # that case the mixture might differ slightly from the sum of the sources.
    # For source separation training data it is important that the mixture is exaclty
    # the sum of the sources.
    # Add `-v 1` to tell sox not to scale the audio (this also prevents dithering).
    parts_audio = [get_part_filename(chorale_name, p, parts_dir) for p in parts]
    file_args = [arg for part_audio in parts_audio for arg in ['-v', '1', part_audio]]
    subprocess.run(['sox', '-m'] + file_args + [str(mix_output_dir / f'{chorale_name}_mix.wav')], check=True, stdout=subprocess.DEVNULL)

if __name__ == "__main__":
    assert music21.VERSION[3] == 'fix_chorales', 'Please use fixed music21 version from matangover/music21'
    main()