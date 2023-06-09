from fastapi import APIRouter, Query, Path
from models.course import CourseResponseSchema
from models.chapter import ChapterResponseSchema
from models.rating import Rating
from config.db import conn 
from schemas.course import serializeDict, serializeList
from bson import ObjectId
from enum import Enum
from fastapi.responses import JSONResponse

course = APIRouter()

class SortByOptions(str, Enum):
    name = "name"
    date = "date"
    rating = "rating"

"""API to return Course Information"""
@course.get('/course')
async def list_courses(
    sort_by: SortByOptions = Query("name", description="Sort courses by name, date or rating. Default is by name."),
    domain : str = Query(None, description="Filter courses by domain name")
):
    descending_sort_for = ["date", "rating"]
    sort_order = -1 if sort_by in descending_sort_for else 1
    sort_by = "overall_rating" if sort_by=="rating" else sort_by
    
    pipeline = [
        {
            "$lookup": {
                "from": "chapter",
                "localField": "_id",
                "foreignField": "course_id",
                "as": "chapters"
            }
        },
        {
            "$sort": {
                sort_by : sort_order
            }
        }
    ]

    if domain is not None:
        pipeline.append({
            "$match": {
                "domain": {
                    "$in": [domain]
                }
            }
        })

    # Find query with join
    sorted_documents = conn.kimo.course.aggregate(pipeline)

    resp = []
    for item in sorted_documents:
        item["_id"] = str(item["_id"])
        item["chapters"] = serializeList(item["chapters"])
        new_data = dict(CourseResponseSchema.parse_obj(item))
        resp.append(new_data)

    return resp


"""Path API to return a specific Course's Information"""
@course.get('/course/{course_id}')
async def list_course(
    course_id : str = Path(..., description="ObjectID of the course")
):
    try:
        course = conn.kimo.course.find_one({"_id": ObjectId(course_id)})
        if course is not None:
            chapters_count = conn.kimo.chapter.count_documents({"course_id": ObjectId(course_id)})
            course["total_chapters"] = chapters_count
            return serializeDict(course)
        else:
            error_message = {"error": "Course not found"}
            return JSONResponse(content=error_message, status_code=404)
    except Exception as e:
        error_message = {"error": str(e)}
        return JSONResponse(content=error_message, status_code=400)


"""Query API to fetch chapter Informations"""
@course.get('/chapter')
async def get_chapter(
    name: str = Query("", description="Search chapters by chapter name"),
    course_id: str = Query("", description="Search chapters by courseID"),
    id: str = Query("", description="Search chapters by chapterID"),
):
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "course",
                    "localField": "course_id",
                    "foreignField": "_id",
                    "as": "course_info",
                }
            }
        ]

        filters = {}
        if name != "":
            filters["name"] = name
        
        if course_id != "":
            filters["course_id"] = ObjectId(course_id)

        if id != "":
            filters["_id"] = ObjectId(id)
            
        if filters is not None:
            pipeline.append({
                "$match": filters
            })

        # Find query with join
        result = conn.kimo.chapter.aggregate(pipeline)

        resp = []
        for item in result:
            item = serializeDict(item)
            item["course_info"] = serializeDict(item["course_info"][0])
            new_data = dict(ChapterResponseSchema.parse_obj(item))
            resp.append(new_data)

        return resp
    except Exception as e:
        error_message = {"error": str(e)}
        return JSONResponse(content=error_message, status_code=400)
    

"""Path API to fetch a specific chapter Information"""
@course.get('/chapter/{chapter_id}')
async def get_chapter(
    chapter_id: str = Path(..., description="Search chapters by chapterID"),
):
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "course",
                    "localField": "course_id",
                    "foreignField": "_id",
                    "as": "course_info",
                }
            },
            {
                "$match": {
                    "_id" : ObjectId(chapter_id)
                }
            }
        ]

        result = conn.kimo.chapter.aggregate(pipeline)
        chapter_info = next(result, None)
        chapter_info = serializeDict(chapter_info)
        chapter_info["course_info"] = serializeDict(chapter_info["course_info"][0])
        new_data = dict(ChapterResponseSchema.parse_obj(chapter_info))
        return new_data
    except Exception as e:
        error_message = {"error": str(e)}
        return JSONResponse(content=error_message, status_code=400)
    

"""API to rate a specific chapter by chapter ID """
@course.post('/rating/chapter/{chapter_id}')
async def create_course(rating: Rating, chapter_id: str = Path(..., description="ChapterID of a specific chapter")):
    try:
        pipeline = [
            {
                "$lookup": {
                    "from": "rating",
                    "localField": "_id",
                    "foreignField": "chapter_id",
                    "as": "rating_info",
                }
            },
            {
                '$unwind': '$rating_info'
            },
            {
                "$match": {
                    "_id" : ObjectId(chapter_id),
                    'rating_info.user': rating.user
                }
            }
        ]

        result = conn.kimo.chapter.aggregate(pipeline)
        chapter_info = next(result, None)
        if chapter_info is None:
            chapter = conn.kimo.chapter.find_one({"_id": ObjectId(chapter_id)})
            if chapter is not None:
                rating_data = {
                    "course_id" : chapter["course_id"],
                    "chapter_id" : chapter["_id"],
                    "user" : rating.user,
                    "point" : rating.point
                }
                conn.kimo.rating.insert_one(rating_data)
                update_overall_rating(chapter["course_id"])
                return JSONResponse(content={"success" : "Rating details updated into the system"}, status_code=200)
            else:
                error_message = {"error": "Chapter not found"}
                return JSONResponse(content=error_message, status_code=404)
        else:
            filter = {'_id': chapter_info["rating_info"]["_id"]}
            update = {'$set': {'point': int(rating.point)}}
            conn.kimo.rating.update_one(filter, update)
            update_overall_rating(chapter_info["course_id"])
            return JSONResponse(content={"success" : "Rating details updated into the system"}, status_code=200)

    except Exception as e:
        error_message = {"error": str(e)}
        return JSONResponse(content=error_message, status_code=400)


def update_overall_rating(course_id : ObjectId):
    try:
        ratings = conn.kimo.rating.find({"course_id": course_id})
        total_rating = 0
        cnt = 0
        for rating in ratings:
            total_rating += int(rating["point"])
            cnt += 1

        overall_rating =  (total_rating // cnt) if cnt > 0 else 0
        filter = {'_id': course_id}
        update = {'$set': {'overall_rating': int(overall_rating)}}
        conn.kimo.course.update_one(filter, update)
        return True
    except Exception as e:
        print(e)
        return False
