""" Use Apple's Vision Framework via PyObjC to detect text in images 
To use:
python3 -m pip install pyobjc-core pyobjc-framework-Quartz pyobjc-framework-Vision wurlitzer
"""

import pathlib

import Quartz
import Vision
from Cocoa import NSURL
from Foundation import NSDictionary
# needed to capture system-level stderr
from wurlitzer import pipes

def image_to_text(img_path, languages=None):
    if languages is None:
        languages = ["ja-JP", "en-US"]

    input_url = NSURL.fileURLWithPath_(img_path)

    with pipes() as (out, err):
        input_image = Quartz.CIImage.imageWithContentsOfURL_(input_url)

    vision_options = NSDictionary.dictionaryWithDictionary_({})
    vision_handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(
        input_image, vision_options
    )

    results = []
    handler = make_request_handler(results)

    vision_request = Vision.VNRecognizeTextRequest.alloc().initWithCompletionHandler_(handler)

    vision_request.setRecognitionLanguages_(languages)
    vision_request.setUsesLanguageCorrection_(True)

    # 精度優先
    vision_request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)

    error = vision_handler.performRequests_error_([vision_request], None)

    return results

def make_request_handler(results):
    """ results: list to store results """
    if not isinstance(results, list):
        raise ValueError("results must be a list")

    def handler(request, error):
        if error:
            print(f"Error! {error}")
        else:
            observations = request.results()
            for text_observation in observations:
                recognized_text = text_observation.topCandidates_(1)[0]
                results.append([recognized_text.string(), recognized_text.confidence()])
    return handler


def main():
    import sys
    import pathlib

    img_path = pathlib.Path(sys.argv[1])
    if not img_path.is_file():
        sys.exit("Invalid image path")
    img_path = str(img_path.resolve())
    results = image_to_text(img_path, languages=["ja-JP", "en-US"])
    print(results)


if __name__ == "__main__":
    main()